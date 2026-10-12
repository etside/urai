package io.github.tukitattu.urai;

import android.app.Activity;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public class SettingsActivity extends Activity {
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        ScrollView sv = new ScrollView(this);
        LinearLayout L = new LinearLayout(this);
        L.setOrientation(LinearLayout.VERTICAL);
        L.setPadding(48, 48, 48, 48);
        sv.addView(L);
        setContentView(sv);

        TextView t1 = new TextView(this);
        t1.setText("Urai server URL (LAN: http://<host>:8777/  emulator: http://10.0.2.2:8777/)");
        L.addView(t1);
        final EditText ep = new EditText(this);
        ep.setSingleLine(true);
        L.addView(ep);

        TextView t2 = new TextView(this);
        t2.setText("API key (same as server URAI_API_KEY; empty if none)");
        L.addView(t2);
        final EditText key = new EditText(this);
        key.setSingleLine(true);
        L.addView(key);

        final SharedPreferences p = getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE);
        ep.setText(p.getString(MainActivity.KEY_EP, MainActivity.DEFAULT_EP));
        key.setText(p.getString(MainActivity.KEY_APIKEY, ""));

        Button save = new Button(this);
        save.setText("Save");
        save.setOnClickListener(v -> {
            String u = ep.getText().toString().trim();
            if (!u.endsWith("/")) u += "/";
            p.edit().putString(MainActivity.KEY_EP, u)
                    .putString(MainActivity.KEY_APIKEY, key.getText().toString().trim())
                    .apply();
            finish();
        });
        L.addView(save);
    }
}
