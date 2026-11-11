#import <Foundation/Foundation.h>

/// Runs SciCal's Python engine inside the app (embedded CPython) and shows it in the Tauri web view.
/// Call +start once, before the Tauri app starts (see patch_ios.py, which adds the call to main.mm).
@interface SciCalEngine : NSObject
+ (void)start;
@end
