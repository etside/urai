package io.github.tukitattu.urai;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.TextUtils;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;

import java.io.File;
import java.io.IOException;
import java.net.URI;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

import io.github.tukitattu.urai.cyber.CyberActivity;

public class MainActivity extends Activity {
    public static final String PREFS = "urai";
    public static final String KEY_EP = "endpoint";
    public static final String KEY_APIKEY = "apikey";
    // emulator loopback default; real devices get the hosted endpoint below
    static final String EMULATOR_EP = "http://10.0.2.2:8777/";
    static final String DEFAULT_EP = "https://urai.daddyai.online/";

    private WebView web;
    private ValueCallback<Uri[]> filePathCallback;
    private Uri cameraUri;
    private static final int REQ_FILE = 1001;

    // Credentials for the endpoint currently loaded, used by the injected
    // bridge. Kept in sync with SharedPreferences in applySaved().
    private String savedEp = DEFAULT_EP;
    private String savedKey = "";
    private String currentEp;
    private String currentKey;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);

        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        // Native bottom navigation: the WebView is the content, these entries
        // stay reachable even if the page fails to load.
        LinearLayout nav = new LinearLayout(this);
        nav.setOrientation(LinearLayout.HORIZONTAL);
        nav.addView(navButton("Home", v -> web.reload()), navParams());
        nav.addView(navButton("Settings", v ->
                startActivity(new Intent(this, SettingsActivity.class))), navParams());
        nav.addView(navButton("Cyber guard", v ->
                startActivity(new Intent(this, CyberActivity.class))), navParams());
        root.addView(nav, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb,
                                             FileChooserParams p) {
                if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                filePathCallback = cb;
                ensureCameraPermission();
                Intent gallery = new Intent(Intent.ACTION_GET_CONTENT);
                gallery.addCategory(Intent.CATEGORY_OPENABLE);
                gallery.setType("image/*");
                Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                try {
                    File photo = createPhotoFile();
                    cameraUri = FileProvider.getUriForFile(MainActivity.this,
                            getPackageName() + ".files", photo);
                    camera.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
                } catch (IOException e) {
                    cameraUri = null;
                }
                Intent chooser = Intent.createChooser(gallery, "Picture for Urai");
                if (cameraUri != null && camera.resolveActivity(getPackageManager()) != null) {
                    chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{camera});
                }
                startActivityForResult(chooser, REQ_FILE);
                return true;
            }
        });

        installWebViewClient();
        applySaved(true);
    }

    private Button navButton(String label, View.OnClickListener onClick) {
        Button btn = new Button(this);
        btn.setText(label);
        btn.setAllCaps(false);
        btn.setOnClickListener(onClick);
        return btn;
    }

    private LinearLayout.LayoutParams navParams() {
        return new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
    }

    private void ensureCameraPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.CAMERA}, 7);
        }
    }

    private File createPhotoFile() throws IOException {
        String name = "urai_" + new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date());
        File dir = getExternalFilesDir(Environment.DIRECTORY_PICTURES);
        return File.createTempFile(name, ".jpg", dir);
    }

    /** Read endpoint + key, then (re)load or re-inject. A reload only happens
     *  when the configured endpoint/key actually changed, so returning from
     *  Settings/file-picker does not blow away an in-progress page. */
    private void applySaved(boolean firstRun) {
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        savedEp = p.getString(KEY_EP, defaultEndpoint());
        savedKey = p.getString(KEY_APIKEY, "");
        if (savedEp == null || savedEp.trim().isEmpty()) savedEp = defaultEndpoint();

        boolean changed = !savedEp.equals(currentEp) || !savedKey.equals(currentKey);
        if (firstRun || changed || web.getUrl() == null) {
            currentEp = savedEp;
            currentKey = savedKey;
            web.loadUrl(savedEp);
        } else {
            // Same origin: refresh the stored credentials in place. The page
            // may already be booted, so only re-boot a not-yet-booted client.
            web.evaluateJavascript(credScript(), null);
        }
    }

    private void installWebViewClient() {
        web.setWebViewClient(new WebViewClient() {
            // onPageStarted fires before the page's own scripts run, so the
            // shared api.js sees urai_ep/urai_key at load time. Only inject
            // for the endpoint we actually configured (never for redirects to
            // third parties, e.g. an external login page).
            @Override
            public void onPageStarted(WebView v, String url, android.graphics.Bitmap favicon) {
                if (isEndpointUrl(url)) v.evaluateJavascript(credScript(), null);
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                if (!isEndpointUrl(url)) return;
                // Set credentials, then hand control to the frontend's own
                // boot(). `window.Urai.boot` is defined by the loaded
                // frontend (frontend/api.js); we no longer call an undefined
                // global `boot`.
                v.evaluateJavascript(credScript() + bootScript(), null);
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req != null && req.isForMainFrame()) {
                    showLoadError(savedEp, err != null ? err.getDescription() : "network error");
                }
            }

            @SuppressWarnings("deprecation")
            @Override
            public void onReceivedError(WebView v, int code, String desc, String failingUrl) {
                if (Build.VERSION.SDK_INT >= 23) return; // handled above
                if (failingUrl != null && failingUrl.equals(savedEp)) showLoadError(savedEp, desc);
            }

            @Override
            public void onReceivedHttpError(WebView v, WebResourceRequest req, WebResourceResponse res) {
                if (req != null && req.isForMainFrame() && res != null
                        && res.getStatusCode() >= 400) {
                    showLoadError(savedEp, "HTTP " + res.getStatusCode());
                }
            }
        });
    }

    private String defaultEndpoint() {
        boolean emulator = Build.FINGERPRINT.contains("generic")
                || Build.PRODUCT.contains("sdk")
                || Build.MODEL.contains("Emulator")
                || Build.MODEL.contains("Android SDK");
        return emulator ? EMULATOR_EP : DEFAULT_EP;
    }

    /** True when the loaded URL shares scheme/host/port with the configured
     *  endpoint, i.e. the origin whose localStorage we own. */
    private boolean isEndpointUrl(String url) {
        if (url == null || savedEp == null) return false;
        try {
            URI loaded = new URI(url);
            URI ep = new URI(savedEp);
            if (loaded.getScheme() == null || ep.getScheme() == null) return false;
            if (!loaded.getScheme().equalsIgnoreCase(ep.getScheme())) return false;
            String lh = loaded.getHost();
            String eh = ep.getHost();
            if (lh == null || eh == null) return url.startsWith(savedEp);
            return lh.equalsIgnoreCase(eh) && defaultPort(loaded) == defaultPort(ep);
        } catch (Exception e) {
            return url.startsWith(savedEp);
        }
    }

    private static int defaultPort(URI u) {
        if (u.getPort() != -1) return u.getPort();
        String scheme = u.getScheme() == null ? "" : u.getScheme().toLowerCase(Locale.US);
        if (scheme.equals("https")) return 443;
        if (scheme.equals("http")) return 80;
        return -1;
    }

    private String credScript() {
        return "(function(){try{localStorage.setItem('urai_ep',"
                + JSONObject.quote(savedEp) + ");localStorage.setItem('urai_key',"
                + JSONObject.quote(savedKey) + ");}catch(e){}})();";
    }

    private String bootScript() {
        return "(function(){try{var u=window.Urai;"
                + "var f=(u&&typeof u.boot==='function')?u.boot:"
                + "(typeof window.boot==='function'?window.boot:null);"
                + "if(f&&!window.__uraiBooted){window.__uraiBooted=true;f.call(u||window);}"
                + "}catch(e){}})();";
    }

    // Never leave the user on a blank white screen: explain and offer retry.
    private void showLoadError(String ep, CharSequence why) {
        String html = "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
                + "<body style='font-family:system-ui,sans-serif;background:#212121;color:#ececec;"
                + "margin:0;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center'>"
                + "<div style='padding:24px;max-width:460px'>"
                + "<h2 style='color:#10a37f;margin:0 0 8px'>Urai can&rsquo;t reach the server</h2>"
                + "<p style='color:#8e8ea0;font-size:14px;word-break:break-all'>Tried <b>"
                + TextUtils.htmlEncode(String.valueOf(ep)) + "</b></p>"
                + "<p style='color:#8e8ea0;font-size:13px'>"
                + TextUtils.htmlEncode(String.valueOf(why)) + "</p>"
                + "<p style='color:#ececec;font-size:14px;margin-top:16px'>Open the <b>&#8942; menu &rarr; Settings</b> "
                + "and set your Urai endpoint (for example <b>http://192.168.x.x:8777/</b> on your LAN).</p>"
                + "<button onclick='location.reload()' style='margin-top:16px;padding:10px 18px;border:0;"
                + "border-radius:8px;background:#10a37f;color:#fff;font-size:15px'>Retry</button>"
                + "</div></body>";
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req != REQ_FILE || filePathCallback == null) return;
        Uri[] out = null;
        if (res == RESULT_OK) {
            if (data != null && data.getData() != null) out = new Uri[]{data.getData()};
            else if (cameraUri != null) out = new Uri[]{cameraUri};
        }
        filePathCallback.onReceiveValue(out);
        filePathCallback = null;
        cameraUri = null;
    }

    @Override
    public boolean onCreateOptionsMenu(Menu m) {
        m.add(0, 1, 0, "Settings").setShowAsAction(MenuItem.SHOW_AS_ACTION_NEVER);
        m.add(0, 2, 0, "Reload").setShowAsAction(MenuItem.SHOW_AS_ACTION_NEVER);
        m.add(0, 3, 0, "Cyber guard").setShowAsAction(MenuItem.SHOW_AS_ACTION_NEVER);
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem it) {
        if (it.getItemId() == 1) startActivity(new Intent(this, SettingsActivity.class));
        else if (it.getItemId() == 3) startActivity(new Intent(this, CyberActivity.class));
        else web.reload();
        return true;
    }

    @Override
    protected void onResume() {
        super.onResume();
        applySaved(false);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    // tiny JSON string escaper (avoids org.json import issues on old APIs)
    static class JSONObject {
        static String quote(String s) {
            StringBuilder o = new StringBuilder("\"");
            for (char c : s.toCharArray()) {
                switch (c) {
                    case '"': o.append("\\\""); break;
                    case '\\': o.append("\\\\"); break;
                    case '\n': o.append("\\n"); break;
                    case '\r': o.append("\\r"); break;
                    default: o.append(c);
                }
            }
            return o.append("\"").toString();
        }
    }
}
