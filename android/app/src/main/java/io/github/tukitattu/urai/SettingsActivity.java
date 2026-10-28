package io.github.tukitattu.urai;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.SpannableString;
import android.text.style.StyleSpan;
import android.view.Gravity;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class SettingsActivity extends Activity {

    static final String PREFS_CYBER = "cyber";
    static final String KEY_OLLAMA  = "ollama_url";

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        ScrollView sv = new ScrollView(this);
        LinearLayout L = new LinearLayout(this);
        L.setOrientation(LinearLayout.VERTICAL);
        L.setPadding(48, 56, 48, 48);
        sv.addView(L);
        setContentView(sv);

        final SharedPreferences p = getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE);

        // ── Title ─────────────────────────────────────────────────────────
        TextView title = new TextView(this);
        title.setText("Urai Settings");
        title.setTextSize(20);
        title.setTypeface(null, Typeface.BOLD);
        title.setPadding(0, 0, 0, 24);
        L.addView(title);

        // ── Urai server section ───────────────────────────────────────────
        L.addView(sectionHeader("Urai Server"));

        L.addView(label("Server URL"));
        L.addView(sublabel("LAN: http://192.168.x.x:8777   Emulator: http://10.0.2.2:8777"));
        final EditText ep = editText(p.getString(MainActivity.KEY_EP, MainActivity.DEFAULT_EP));
        L.addView(ep);

        L.addView(label("API Key"));
        L.addView(sublabel("Your urai_… token (from Settings → API Keys in the Studio)"));
        final EditText apiKey = editText(p.getString(MainActivity.KEY_APIKEY, ""));
        apiKey.setInputType(android.text.InputType.TYPE_CLASS_TEXT |
                            android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        L.addView(apiKey);

        // Connection status label
        final TextView connStatus = new TextView(this);
        connStatus.setTextSize(13);
        connStatus.setPadding(0, 8, 0, 0);
        connStatus.setTextColor(Color.parseColor("#888888"));
        L.addView(connStatus);

        // Buttons row
        LinearLayout btnRow = new LinearLayout(this);
        btnRow.setOrientation(LinearLayout.HORIZONTAL);
        btnRow.setPadding(0, 12, 0, 0);

        Button save = button("Save");
        save.setOnClickListener(v -> {
            String u = ep.getText().toString().trim();
            if (!u.endsWith("/")) u += "/";
            p.edit()
                .putString(MainActivity.KEY_EP, u)
                .putString(MainActivity.KEY_APIKEY, apiKey.getText().toString().trim())
                .apply();
            Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show();
            finish();
        });

        Button test = button("Test connection");
        test.setOnClickListener(v -> {
            String u = ep.getText().toString().trim();
            if (!u.endsWith("/")) u += "/";
            final String healthUrl = u + "health";
            connStatus.setText("Testing…");
            connStatus.setTextColor(Color.parseColor("#888888"));
            new Thread(() -> {
                String result;
                try {
                    HttpURLConnection conn = (HttpURLConnection) new URL(healthUrl).openConnection();
                    conn.setConnectTimeout(5000);
                    conn.setReadTimeout(5000);
                    InputStream is = conn.getInputStream();
                    byte[] bytes = new byte[512];
                    int n = is.read(bytes);
                    String body = n > 0 ? new String(bytes, 0, n, StandardCharsets.UTF_8) : "";
                    if (body.contains("ok")) result = "✓ Connected";
                    else result = "✓ Responded: " + body.substring(0, Math.min(40, body.length()));
                } catch (Exception e) {
                    result = "✗ " + e.getMessage();
                }
                final String r = result;
                new Handler(Looper.getMainLooper()).post(() -> {
                    connStatus.setText(r);
                    connStatus.setTextColor(r.startsWith("✓")
                            ? Color.parseColor("#10a37f") : Color.parseColor("#e05e5e"));
                });
            }).start();
        });

        btnRow.addView(save);
        btnRow.addView(spacer(12));
        btnRow.addView(test);
        L.addView(btnRow);

        // ── OpenAI-compatible info ────────────────────────────────────────
        L.addView(spacer(24));
        L.addView(sectionHeader("OpenAI-Compatible API"));
        L.addView(sublabel("Point any OpenAI client at your Urai server:"));

        String urlVal = p.getString(MainActivity.KEY_EP, MainActivity.DEFAULT_EP);
        if (urlVal.endsWith("/")) urlVal = urlVal.substring(0, urlVal.length()-1);
        final String baseUrl = urlVal + "/v1";

        TextView compatInfo = monoBlock(
            "Base URL: " + baseUrl + "\n" +
            "API Key:  your urai_… token\n" +
            "Model:    urai  (or urai-fast, urai-ultra, urai-cyber)");
        L.addView(compatInfo);

        Button copyUrl = button("Copy base URL");
        copyUrl.setOnClickListener(v -> {
            android.content.ClipboardManager cm = (android.content.ClipboardManager)
                    getSystemService(CLIPBOARD_SERVICE);
            cm.setPrimaryClip(android.content.ClipData.newPlainText("urai_base_url", baseUrl));
            Toast.makeText(this, "Copied: " + baseUrl, Toast.LENGTH_SHORT).show();
        });
        L.addView(copyUrl);

        // ── Ollama / GGUF section ─────────────────────────────────────────
        L.addView(spacer(24));
        L.addView(sectionHeader("Ollama / GGUF Import"));
        L.addView(sublabel("Use your Urai GGUFs in the Ollama Android app for fully offline inference."));

        L.addView(label("Ollama server URL (optional)"));
        L.addView(sublabel("If running Ollama on this device or LAN (e.g. http://localhost:11434)"));
        final EditText ollamaUrl = editText(
                getSharedPreferences(PREFS_CYBER, MODE_PRIVATE).getString(KEY_OLLAMA, ""));
        L.addView(ollamaUrl);

        Button saveOllama = button("Save Ollama URL");
        saveOllama.setOnClickListener(v -> {
            getSharedPreferences(PREFS_CYBER, MODE_PRIVATE).edit()
                .putString(KEY_OLLAMA, ollamaUrl.getText().toString().trim())
                .apply();
            Toast.makeText(this, "Ollama URL saved", Toast.LENGTH_SHORT).show();
        });
        L.addView(saveOllama);

        L.addView(spacer(12));
        L.addView(sublabel("How to import a Urai GGUF into Ollama:"));
        L.addView(monoBlock(
            "# 1. Download a GGUF from your Urai server\n" +
            "curl -L " + urlVal + "/v1/models/qwen3-4b/download \\\n" +
            "     -o qwen3-4b.gguf\n\n" +
            "# 2. Create Modelfile\n" +
            "echo 'FROM ./qwen3-4b.gguf' > Modelfile\n" +
            "echo 'PARAMETER num_ctx 4096' >> Modelfile\n\n" +
            "# 3. Import\n" +
            "ollama create qwen3-4b -f Modelfile\n\n" +
            "# 4. Run\n" +
            "ollama run qwen3-4b"));
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private TextView sectionHeader(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(13);
        tv.setTypeface(null, Typeface.BOLD);
        tv.setTextColor(Color.parseColor("#888888"));
        tv.setAllCaps(true);
        tv.setLetterSpacing(0.08f);
        tv.setPadding(0, 8, 0, 6);
        return tv;
    }

    private TextView label(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(14);
        tv.setTypeface(null, Typeface.BOLD);
        tv.setPadding(0, 12, 0, 2);
        return tv;
    }

    private TextView sublabel(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(12);
        tv.setTextColor(Color.parseColor("#888888"));
        tv.setPadding(0, 0, 0, 4);
        return tv;
    }

    private EditText editText(String value) {
        EditText et = new EditText(this);
        et.setText(value);
        et.setSingleLine(true);
        et.setTextSize(14);
        et.setPadding(16, 12, 16, 12);
        et.setBackgroundColor(Color.parseColor("#F5F5F5"));
        return et;
    }

    private Button button(String text) {
        Button btn = new Button(this);
        btn.setText(text);
        btn.setTextSize(13);
        return btn;
    }

    private TextView monoBlock(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTypeface(Typeface.MONOSPACE);
        tv.setTextSize(11);
        tv.setTextColor(Color.parseColor("#333333"));
        tv.setBackgroundColor(Color.parseColor("#F0F0F0"));
        tv.setPadding(20, 16, 20, 16);
        tv.setLineSpacing(4, 1);
        return tv;
    }

    private android.view.View spacer(int dp) {
        android.view.View v = new android.view.View(this);
        int px = (int)(dp * getResources().getDisplayMetrics().density);
        v.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, px));
        return v;
    }
}
