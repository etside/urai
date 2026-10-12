package io.github.tukitattu.urai;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.Menu;
import android.view.MenuItem;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
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
    static final String DEFAULT_EP = "http://10.0.2.2:8777/";

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
        final String ep = p.getString(KEY_EP, DEFAULT_EP);
        final String key = p.getString(KEY_APIKEY, "");
        web.loadUrl(ep);
        // inject saved endpoint+key into the webapp's localStorage, then reboot it
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView v, String url) {
                String js = "(function(){try{localStorage.urai_ep="
                        + JSONObject.quote(ep) + ";localStorage.urai_key="
                        + JSONObject.quote(key) + ";if(window.boot)boot();}catch(e){}})();";
                v.evaluateJavascript(js, null);
            }
        });
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
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem it) {
        if (it.getItemId() == 1) startActivity(new Intent(this, SettingsActivity.class));
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
