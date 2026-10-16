package io.github.tukitattu.urai.cyber;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.provider.Settings;

import java.io.DataOutputStream;

/** Blocking, honestly tiered:
 *  1. Shizuku (system app-ops shell, user grants once) — real silent block.
 *  2. Root shell — same appops commands, if available.
 *  3. Settings deep-link — user taps twice, always works, no special rights.
 *  Detection never claims blocking powers the device cannot grant. */
public final class BlockHelper {
    private BlockHelper() {}

    public static String block(Context ctx, String pkg, String op) {
        String appOp = toAppOp(op);
        // 1. Shizuku path (moe.shizuku.privileged.api on classpath)
        try {
            Class<?> shizuku = Class.forName("moe.shizuku.privileged.api.Shizuku");
            Object granted = shizuku.getMethod("checkSelfPermission").invoke(null);
            if (Boolean.TRUE.equals(granted)) {
                String[] cmd = {"appops", "set", pkg, appOp, "ignore"};
                Object proc = shizuku.getMethod("newProcess", String[].class, String[].class, String.class)
                        .invoke(null, (Object) cmd, null, null);
                int rc = ((Process) proc).waitFor();
                if (rc == 0) return "blocked via Shizuku: " + pkg + " " + appOp;
            }
        } catch (Throwable ignored) {
            // Shizuku absent or not granted — fall through
        }
        // 2. Root path
        try {
            Process su = Runtime.getRuntime().exec("su");
            DataOutputStream os = new DataOutputStream(su.getOutputStream());
            os.writeBytes("appops set " + pkg + " " + appOp + " ignore\n");
            os.writeBytes("exit\n");
            os.flush();
            if (su.waitFor() == 0) return "blocked via root: " + pkg + " " + appOp;
        } catch (Throwable ignored) {
        }
        // 3. Settings deep-link (always available)
        try {
            Intent i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + pkg));
            i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(i);
            return "needs-you: opened system settings for " + pkg + " — revoke " + appOp + " there";
        } catch (Exception e) {
            return "failed: " + e.getMessage();
        }
    }

    private static String toAppOp(String op) {
        if (op == null) return "COARSE_LOCATION";
        String u = op.toUpperCase();
        if (u.contains("RECORD_AUDIO")) return "RECORD_AUDIO";
        if (u.contains("CAMERA")) return "CAMERA";
        if (u.contains("FINE_LOCATION")) return "FINE_LOCATION";
        if (u.contains("BACKGROUND_LOCATION")) return "BACKGROUND_LOCATION";
        if (u.contains("COARSE_LOCATION")) return "COARSE_LOCATION";
        if (u.contains("BODY_SENSORS")) return "BODY_SENSORS";
        if (u.contains("ACTIVITY_RECOGNITION")) return "ACTIVITY_RECOGNITION";
        if (u.contains("READ_SMS")) return "READ_SMS";
        if (u.contains("READ_CONTACTS")) return "READ_CONTACTS";
        return "COARSE_LOCATION";
    }

    public static boolean isSystemApp(PackageManager pm, String pkg) {
        try {
            return (pm.getApplicationInfo(pkg, 0).flags
                    & (android.content.pm.ApplicationInfo.FLAG_SYSTEM
                       | android.content.pm.ApplicationInfo.FLAG_UPDATED_SYSTEM_APP)) != 0;
        } catch (Exception e) {
            return true;
        }
    }
}
