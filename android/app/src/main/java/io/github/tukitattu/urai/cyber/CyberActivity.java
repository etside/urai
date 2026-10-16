package io.github.tukitattu.urai.cyber;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.AppOpsManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Process;
import android.provider.Settings;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

import io.github.tukitattu.urai.MainActivity;
import io.github.tukitattu.urai.SettingsActivity;

/** CyberUrai console: ranked app list, per-app detail, block prompt,
 *  one-tap "Ask CyberUrai" backend analysis. Programmatic UI, no XML. */
public class CyberActivity extends Activity {
    private static final int REQ_NOTIF = 201;

    private static class Row {
        String pkg, label;
        int score;
        List<String> reasons;
    }

    private RowAdapter adapter;

    @Override
    protected void onCreate(Bundle b) {
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
        Button scan = new Button(this);
        scan.setText("Scan");
        scan.setOnClickListener(v -> load());
        Button svc = new Button(this);
        svc.setText("Start monitor");
        svc.setOnClickListener(v -> startMonitor());
        bar.addView(scan);
        bar.addView(svc);
        if (!hasUsageAccess()) {
            Button usage = new Button(this);
            usage.setText("Grant usage access");
            usage.setOnClickListener(v -> openUsageAccessSettings());
            bar.addView(usage);
        }
        root.addView(bar);

        // RecyclerView instead of a weighted ListView nested in a ScrollView:
        // nested scrolling is handled correctly and there is one scroll owner.
        RecyclerView list = new RecyclerView(this);
        list.setLayoutManager(new LinearLayoutManager(this));
        adapter = new RowAdapter();
        list.setAdapter(adapter);
        root.addView(list, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);

        String pkg = getIntent().getStringExtra("pkg");
        String op = getIntent().getStringExtra("op");
        load();
        if (pkg != null) showDetail(pkg, op);
    }

    private void startMonitor() {
        if (Build.VERSION.SDK_INT >= 33
                && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIF);
            return;
        }
        launchMonitor();
    }

    @Override
    public void onRequestPermissionsResult(int req, @NonNull String[] perms, @NonNull int[] res) {
        super.onRequestPermissionsResult(req, perms, res);
        if (req == REQ_NOTIF) launchMonitor(); // run even if denied: FGS still runs
    }

    private void launchMonitor() {
        Intent si = new Intent(this, PrivacyMonitorService.class);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(si);
        else startService(si);
        Toast.makeText(this, "Monitor started", Toast.LENGTH_SHORT).show();
    }

    private boolean hasUsageAccess() {
        try {
            AppOpsManager ops = (AppOpsManager) getSystemService(Context.APP_OPS_SERVICE);
            if (ops == null) return false;
            int mode;
            if (Build.VERSION.SDK_INT >= 29) {
                mode = ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                        Process.myUid(), getPackageName());
            } else {
                mode = ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                        Process.myUid(), getPackageName());
            }
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Exception e) {
            return false;
        }
    }

    private void openUsageAccessSettings() {
        try {
            startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
        } catch (Exception e) {
            Toast.makeText(this, "No usage-access settings on this device",
                    Toast.LENGTH_SHORT).show();
        }
    }

    private void load() {
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
                adapter.submit(rows);
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
            SharedPreferences sp = getSharedPreferences(
                    SettingsActivity.CYBER_PREFS, MODE_PRIVATE);
            String url = sp.getString(SettingsActivity.CYBER_URL, "");
            String key = sp.getString(SettingsActivity.CYBER_KEY, "");
            // Fall back to the main endpoint/key if the guard prefs were never
            // written (e.g. app upgraded from an older build).
            if (url == null || url.isEmpty() || key == null || key.isEmpty()) {
                SharedPreferences mp = getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE);
                if (url == null || url.isEmpty()) {
                    url = mp.getString(MainActivity.KEY_EP, "https://urai.daddyai.online/");
                }
                if (key == null || key.isEmpty()) {
                    key = mp.getString(MainActivity.KEY_APIKEY, "");
                }
            }
            String ans = CyberUraiClient.analyze(url, key, pkg, op);
            runOnUiThread(() -> new AlertDialog.Builder(this)
                    .setTitle("CyberUrai verdict")
                    .setMessage(ans)
                    .setPositiveButton("OK", null).show());
        }).start();
    }

    /** RecyclerView adapter: no nested scroll, safe inside a fixed-height list. */
    private class RowAdapter extends RecyclerView.Adapter<RowAdapter.VH> {
        private final List<Row> rows = new ArrayList<>();

        void submit(List<Row> fresh) {
            rows.clear();
            rows.addAll(fresh);
            notifyDataSetChanged();
        }

        @NonNull
        @Override
        public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            LinearLayout c = new LinearLayout(CyberActivity.this);
            c.setOrientation(LinearLayout.VERTICAL);
            int p = (int) (12 * getResources().getDisplayMetrics().density);
            c.setPadding(p, p, p, p);
            c.setLayoutParams(new RecyclerView.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT));
            TextView label = new TextView(CyberActivity.this);
            label.setTextSize(16);
            label.setId(android.R.id.text1);
            TextView sub = new TextView(CyberActivity.this);
            sub.setTextSize(12);
            sub.setId(android.R.id.text2);
            c.addView(label);
            c.addView(sub);
            return new VH(c);
        }

        @Override
        public void onBindViewHolder(@NonNull VH h, int position) {
            final Row r = rows.get(position);
            ((TextView) h.itemView.findViewById(android.R.id.text1))
                    .setText(r.label + "  [" + r.score + "]");
            ((TextView) h.itemView.findViewById(android.R.id.text2))
                    .setText(summarize(r.reasons));
            h.itemView.setOnClickListener(v -> showDetail(r.pkg, null));
        }

        @Override
        public int getItemCount() {
            return rows.size();
        }

        private String summarize(List<String> reasons) {
            if (reasons == null || reasons.isEmpty()) return "";
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < reasons.size() && i < 3; i++) {
                if (i > 0) sb.append(" • ");
                sb.append(reasons.get(i));
            }
            return sb.toString();
        }

        class VH extends RecyclerView.ViewHolder {
            VH(@NonNull View v) {
                super(v);
            }
        }
    }
}
