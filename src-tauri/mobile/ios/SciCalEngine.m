// SciCal engine host for iOS. See docs/MOBILE_AND_DESKTOP.md ("iOS") for how the Python runtime gets into the app.
//
// Layout of the app bundle this file expects (made by the "Embed Python" build phase and the staging script):
//   python/lib/python3.13/...        the standard library from BeeWare's Python-Apple-support (Python.xcframework)
//   app/scical/...                   SciCal's Python package
//   app_packages/...                 sympy, mpmath, numpy (iOS builds)
//   scical_client/...                the web client (dist/)
#import "SciCalEngine.h"
#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>
#import <Python/Python.h>
#import <Security/Security.h>

static const int kPreferredPort = 47868;               // keeps the web view's storage address stable between runs
static NSString *volatile gURL = nil;
static NSString *volatile gFailure = nil;

static wchar_t *Wide(NSString *s) { return Py_DecodeLocale(s.UTF8String, NULL); }

static NSString *Token(void) {
    uint8_t bytes[24];
    if (SecRandomCopyBytes(kSecRandomDefault, sizeof bytes, bytes) != errSecSuccess) return nil;
    NSMutableString *out = [NSMutableString string];
    for (size_t i = 0; i < sizeof bytes; i++) [out appendFormat:@"%02x", bytes[i]];
    return out;
}

static NSString *Fail(PyStatus status, PyConfig *config) {
    NSString *message = status.err_msg ? [NSString stringWithUTF8String:status.err_msg] : @"unknown error";
    PyConfig_Clear(config);
    return [NSString stringWithFormat:@"Python could not start: %@", message];
}

/// Start CPython and the SciCal server. Returns nil on success (the address is then in gURL), or a message.
static NSString *StartPython(void) {
    NSString *bundle = NSBundle.mainBundle.resourcePath;
    NSString *support = [NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES) firstObject];
    NSString *docs = [NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES) firstObject];
    NSString *data = [support stringByAppendingPathComponent:@"SciCal/data"];
    NSString *exports = [docs stringByAppendingPathComponent:@"SciCal"];
    NSString *client = [bundle stringByAppendingPathComponent:@"scical_client"];
    NSString *token = Token();
    if (!token) return @"No secure random numbers were available.";
    [NSFileManager.defaultManager createDirectoryAtPath:data withIntermediateDirectories:YES attributes:nil error:nil];
    [NSFileManager.defaultManager createDirectoryAtPath:exports withIntermediateDirectories:YES attributes:nil error:nil];

    NSString *home = [bundle stringByAppendingPathComponent:@"python"];
    NSString *lib = [home stringByAppendingPathComponent:@"lib/python3.13"];
    NSArray<NSString *> *paths = @[
        [lib stringByAppendingPathComponent:@"lib-dynload"], lib,
        [bundle stringByAppendingPathComponent:@"app_packages"], [bundle stringByAppendingPathComponent:@"app"]];

    PyPreConfig pre;
    PyPreConfig_InitIsolatedConfig(&pre);
    pre.utf8_mode = 1;
    pre.configure_locale = 0;
    PyStatus status = Py_PreInitialize(&pre);
    if (PyStatus_Exception(status)) return [NSString stringWithFormat:@"Python pre-initialisation failed: %s", status.err_msg ?: "?"];

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.buffered_stdio = 0;
    config.write_bytecode = 0;
    config.install_signal_handlers = 0;
    status = PyConfig_SetBytesString(&config, &config.home, home.UTF8String);
    if (PyStatus_Exception(status)) return Fail(status, &config);
    config.module_search_paths_set = 1;
    for (NSString *p in paths) {
        wchar_t *w = Wide(p);
        status = PyWideStringList_Append(&config.module_search_paths, w);
        PyMem_RawFree(w);
        if (PyStatus_Exception(status)) return Fail(status, &config);
    }
    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) return [NSString stringWithFormat:@"Python could not start: %s", status.err_msg ?: "?"];

    // Hand the settings over as a JSON file so no quoting is needed, then start the server from Python.
    NSString *argsPath = [NSTemporaryDirectory() stringByAppendingPathComponent:@"scical-engine-args.json"];
    NSString *resultPath = [NSTemporaryDirectory() stringByAppendingPathComponent:@"scical-engine-result.json"];
    NSDictionary *args = @{@"data": data, @"out": exports, @"token": token, @"port": @(kPreferredPort), @"client": client, @"result": resultPath};
    [[NSJSONSerialization dataWithJSONObject:args options:0 error:nil] writeToFile:argsPath atomically:YES];
    [NSFileManager.defaultManager removeItemAtPath:resultPath error:nil];
    NSString *code = [NSString stringWithFormat:
        @"import json, traceback\n"
         "a = json.load(open(%@))\n"
         "try:\n"
         "    from scical import embed\n"
         "    info = embed.start(a['data'], a['out'], a['token'], a['port'], a['client'], 'thread')\n"
         "except BaseException:\n"
         "    info = {'error': traceback.format_exc()}\n"
         "open(a['result'], 'w').write(json.dumps(info))\n",
        [NSString stringWithFormat:@"'%@'", [argsPath stringByReplacingOccurrencesOfString:@"'" withString:@"\\'"]]];
    int rc = PyRun_SimpleString(code.UTF8String);
    PyEval_SaveThread();                                        // let the server's threads run: this thread no longer holds the GIL
    if (rc != 0) return @"The engine's start-up script failed.";

    NSData *raw = [NSData dataWithContentsOfFile:resultPath];
    NSDictionary *info = raw ? [NSJSONSerialization JSONObjectWithData:raw options:0 error:nil] : nil;
    if (![info isKindOfClass:NSDictionary.class]) return @"The engine did not report an address.";
    if (info[@"error"]) return [NSString stringWithFormat:@"The engine failed to start:\n%@", info[@"error"]];
    gURL = info[@"url"];
    return nil;
}

static WKWebView *FindWebView(UIView *view) {
    if ([view isKindOfClass:WKWebView.class]) return (WKWebView *)view;
    for (UIView *sub in view.subviews) {
        WKWebView *found = FindWebView(sub);
        if (found) return found;
    }
    return nil;
}

static WKWebView *CurrentWebView(void) {
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class]) continue;
        for (UIWindow *window in ((UIWindowScene *)scene).windows) {
            WKWebView *found = FindWebView(window);
            if (found) return found;
        }
    }
    return nil;
}

@implementation SciCalEngine

+ (void)start {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        NSDate *begin = NSDate.date;
        NSThread *engine = [[NSThread alloc] initWithBlock:^{
            NSString *problem = StartPython();
            if (problem) gFailure = problem;
        }];
        engine.name = @"scical-engine";
        engine.stackSizeInBytes = 16 * 1024 * 1024;           // SymPy recurses deeply
        [engine start];
        [self pollSince:begin];
    });
}

/// The web view appears a moment after launch and the engine needs a few seconds: look again until both are ready.
+ (void)pollSince:(NSDate *)begin {
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.15 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        WKWebView *web = CurrentWebView();
        NSString *address = gURL, *problem = gFailure;
        if (web && address) {
            [web loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:address]]];
            return;
        }
        if (web && problem) {
            NSData *quoted = [NSJSONSerialization dataWithJSONObject:@[problem] options:0 error:nil];
            NSString *arr = [[NSString alloc] initWithData:quoted encoding:NSUTF8StringEncoding];
            [web evaluateJavaScript:[NSString stringWithFormat:@"window.scicalFailed && window.scicalFailed(%@[0])", arr] completionHandler:nil];
            return;
        }
        if (-[begin timeIntervalSinceNow] < 120) [self pollSince:begin];
    });
}

@end
