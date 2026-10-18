package io.github.tukitattu.urai.cyber;

import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/** CyberUrai console: ranked app list, per-app detail, block prompt,
 *  one-tap "Ask CyberUrai" backend analysis. Programmatic UI, no XML. */
public class CyberActivity extends android.app.Activity {
    private static class Row {
        String pkg, label;
        int score;
        List<String> reasons;
        public String toString() { return label + "  [" + score + "]"; }
    }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (12 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("CyberUrai-v1 — privacy guard");
        title.setTextSize(20);
        root.addView(title);

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        Button scan = new Button(this); scan.setText("Scan");
        scan.setOnClickListener(v -> load((ListView) root.findViewWithTag("list")));
        Button svc = new Button(this); svc.setText("Start monitor");
        svc.setOnClickListener(v -> {
            startForegroundService(new android.content.Intent(this, PrivacyMonitorService.class));
            Toast.makeText(this, "Monitor started", Toast.LENGTH_SHORT).show();
        });
        bar.addView(scan); bar.addView(svc);
        root.addView(bar);

        ListView list = new ListView(this);
        list.setTag("list");
        list.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        root.addView(list);
        setContentView(new ScrollView(this) {{ addView(root); }});

        String pkg = getIntent().getStringExtra("pkg");
        String op = getIntent().getStringExtra("op");
        load(list);
        if (pkg != null) showDetail(pkg, op);
    }

    private void load(ListView list) {
        new Thread(() -> {
            PackageManager pm = getPackageManager();
            List<Row> rows = new ArrayList<>();
            for (ApplicationInfo ai : pm.getInstalledApplications(PackageManager.GET_META_DATA)) {
                if ((ai.flags & ApplicationInfo.FLAG_SYSTEM) != 0) continue;
                Map<String, Object> s = TrackerDB.score(pm, ai.packageName);
                int score = (int) s.get("score");
                if (score <= 0) continue;
                Row r = new Row();
                r.pkg = ai.packageName;
                r.label = String.valueOf(pm.getApplicationLabel(ai));
                r.score = score;
                @SuppressWarnings("unchecked")
                List<String> rs = (List<String>) s.get("reasons");
                r.reasons = rs;
                rows.add(r);
            }
            Collections.sort(rows, Comparator.comparingInt((Row r) -> r.score).reversed());
            runOnUiThread(() -> {
                ArrayAdapter<Row> ad = new ArrayAdapter<>(this,
                        android.R.layout.simple_list_item_1, rows);
                list.setAdapter(ad);
                list.setOnItemClickListener((p, v, pos, id) ->
                        showDetail(rows.get(pos).pkg, null));
                Toast.makeText(this, rows.size() + " flagged apps", Toast.LENGTH_SHORT).show();
            });
        }).start();
    }

    private void showDetail(String pkg, String op) {
        Map<String, Object> s = TrackerDB.score(getPackageManager(), pkg);
        String msg = "package: " + pkg + "\nrisk score: " + s.get("score") + "/100\n\n"
                + android.text.TextUtils.join("\n• ", (List<String>) s.get("reasons"))
                + (op != null ? "\n\nlast access: " + TrackerDB.opLabel(op) : "");
        new AlertDialog.Builder(this)
                .setTitle("Review access")
                .setMessage(msg)
                .setPositiveButton("Block", (d, w) -> {
                    String r = BlockHelper.block(this, pkg, op);
                    Toast.makeText(this, r, Toast.LENGTH_LONG).show();
                })
                .setNeutralButton("Ask CyberUrai", (d, w) -> askBackend(pkg, op))
                .setNegativeButton("Allow", null)
                .show();
    }

    private void askBackend(String pkg, String op) {
        Toast.makeText(this, "Asking CyberUrai…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            SharedPreferences sp = getSharedPreferences("cyber", MODE_PRIVATE);
            String url = sp.getString("url", "https://urai.daddyai.online");
            String key = sp.getString("key", "");
            String ans = CyberUraiClient.analyze(url, key, pkg, op);
            runOnUiThread(() -> new AlertDialog.Builder(this)
                    .setTitle("CyberUrai verdict")
                    .setMessage(ans)
                    .setPositiveButton("OK", null).show());
        }).start();
    }
}
