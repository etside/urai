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
import io.github.tukitattu.urai.cyber.CyberActivity;
import android.provider.MediaStore;
import android.text.TextUtils;
import android.view.Menu;
import android.view.MenuItem;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;
import java.io.File;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public class MainActivity extends Activity {
    static final String PREFS = "urai";
    static final String KEY_EP = "endpoint";
    static final String KEY_APIKEY = "apikey";
    // emulator loopback default; real devices get the hosted endpoint below
    static final String EMULATOR_EP = "http://10.0.2.2:8777/";
    static final String DEFAULT_EP = "https://urai.daddyai.online/";

    private WebView web;
    private ValueCallback<Uri[]> filePathCallback;
    private Uri cameraUri;
    private static final int REQ_FILE = 1001;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        web = new WebView(this);
        setContentView(web);
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
        loadSaved();
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

    private void loadSaved() {
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        final String ep = p.getString(KEY_EP, defaultEndpoint());
        final String key = p.getString(KEY_APIKEY, "");
        // Client MUST be set before the first load, otherwise a failed load
        // renders a blank white page with no way back.
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView v, String url) {
                String js = "(function(){try{localStorage.urai_ep="
                        + JSONObject.quote(ep) + ";localStorage.urai_key="
                        + JSONObject.quote(key)
                        + ";if(typeof boot==='function')boot();}catch(e){}})();";
                v.evaluateJavascript(js, null);
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req != null && req.isForMainFrame()) {
                    showLoadError(ep, err != null ? err.getDescription() : "network error");
                }
            }

            @SuppressWarnings("deprecation")
            @Override
            public void onReceivedError(WebView v, int code, String desc, String failingUrl) {
                showLoadError(ep, desc);
            }

            @Override
            public void onReceivedHttpError(WebView v, WebResourceRequest req, WebResourceResponse res) {
                if (req != null && req.isForMainFrame() && res != null
                        && res.getStatusCode() >= 400) {
                    showLoadError(ep, "HTTP " + res.getStatusCode());
                }
            }
        });
        web.loadUrl(ep);
    }

    private String defaultEndpoint() {
        boolean emulator = Build.FINGERPRINT.contains("generic")
                || Build.PRODUCT.contains("sdk")
                || Build.MODEL.contains("Emulator")
                || Build.MODEL.contains("Android SDK");
        return emulator ? EMULATOR_EP : DEFAULT_EP;
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
        m.add(0, 1, 0, "Settings").setShowAsAction(MenuItem.SHOW_AS_ACTION_ALWAYS);
        m.add(0, 2, 0, "Reload").setShowAsAction(MenuItem.SHOW_AS_ACTION_ALWAYS);
        m.add(0, 3, 0, "Cyber guard");
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
        loadSaved();
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
