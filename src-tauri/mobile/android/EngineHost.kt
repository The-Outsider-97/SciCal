package app.slai.scical

import android.app.Activity
import android.content.res.AssetManager
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.security.SecureRandom
import kotlin.concurrent.thread

/**
 * Runs SciCal's Python engine inside this app (Chaquopy) and shows it in the Tauri web view.
 *
 * The engine listens on 127.0.0.1 only, with a random access token that exists only in this process. The window first shows the
 * start-up page that Tauri serves; as soon as the engine is ready, this class loads the engine's address into the same web view.
 */
object EngineHost {
    private const val TAG = "SciCalEngine"
    private const val PREFERRED_PORT = 47868          // keeps the web view's storage address stable between runs; any free port if taken
    private const val CLIENT_ASSET_DIR = "scical_client"
    private const val SLAI_ASSET_DIR = "scical_slai"     // the part of SLAI the app carries: the STEM agent and the SLDC/SGEO/SDRW exports

    @Volatile private var url: String? = null
    @Volatile private var failure: String? = null
    private var started = false

    fun attach(activity: Activity) {
        if (!started) {
            started = true
            thread(name = "scical-engine", isDaemon = true) { startEngine(activity) }
        }
        pollForWebView(activity, System.currentTimeMillis())
    }

    private fun startEngine(activity: Activity) {
        try {
            if (!Python.isStarted()) Python.start(AndroidPlatform(activity.applicationContext))
            val client = File(activity.filesDir, "client")
            syncAssets(activity.assets, activity.filesDir, CLIENT_ASSET_DIR, "client.version", client, "index.html")
            val slai = File(activity.filesDir, "slai")          // writable: SLAI's agents write their logs relative to it
            syncAssets(activity.assets, activity.filesDir, SLAI_ASSET_DIR, "slai.version", slai, "src/agents/stem_agent.py")
            val data = File(activity.filesDir, "scical-data")
            val exports = activity.getExternalFilesDir("Documents") ?: File(activity.filesDir, "exports")
            val token = ByteArray(24).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
            val embed = Python.getInstance().getModule("scical.embed")
            val info = embed.callAttr("start", data.absolutePath, exports.absolutePath, token, PREFERRED_PORT, client.absolutePath, "thread", slai.absolutePath)
            url = info.callAttr("get", "url").toString()
            Log.i(TAG, "engine ready")
        } catch (e: Throwable) {
            Log.e(TAG, "engine failed", e)
            failure = (e.message ?: e.javaClass.simpleName)
        }
    }

    /** Copy a folder out of the APK (the engine reads files from disk). Done again only when the app version changed. */
    private fun syncAssets(assets: AssetManager, filesDir: File, assetDir: String, markerName: String, target: File, probe: String) {
        val stamp = assets.open("$assetDir/version.txt").bufferedReader().use { it.readText().trim() }
        val marker = File(filesDir, markerName)
        if (marker.isFile && marker.readText() == stamp && File(target, probe).isFile) return
        target.deleteRecursively()
        copyTree(assets, assetDir, target)
        marker.writeText(stamp)
    }

    private fun copyTree(assets: AssetManager, from: String, to: File) {
        val names = assets.list(from) ?: emptyArray()
        if (names.isEmpty()) {
            to.parentFile?.mkdirs()
            assets.open(from).use { input -> to.outputStream().use { input.copyTo(it) } }
            return
        }
        to.mkdirs()
        for (n in names) copyTree(assets, "$from/$n", File(to, n))
    }

    private fun findWebView(v: View?): WebView? {
        if (v is WebView) return v
        if (v is ViewGroup) for (i in 0 until v.childCount) findWebView(v.getChildAt(i))?.let { return it }
        return null
    }

    /** The web view is created a moment after the activity, and the engine takes a few seconds: look again until both are ready. */
    private fun pollForWebView(activity: Activity, since: Long) {
        val handler = Handler(Looper.getMainLooper())
        handler.postDelayed(object : Runnable {
            override fun run() {
                val web = findWebView(activity.window?.decorView)
                val message = failure
                val address = url
                if (web != null && address != null) { web.loadUrl(address); return }
                if (web != null && message != null) {
                    web.evaluateJavascript("window.scicalFailed && window.scicalFailed(${org.json.JSONObject.quote("SciCal could not start: $message")})", null)
                    return
                }
                if (System.currentTimeMillis() - since < 120_000) handler.postDelayed(this, 150)
            }
        }, 150)
    }
}
