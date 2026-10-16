package io.github.tukitattu.urai.cyber;

import android.app.AppOpsManager;
import android.content.Context;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** Watches sensor/data ops across all packages via AppOps callbacks.
 *  startWatchingMode IS callable by third-party apps; onOpChanged reports
 *  the package name. No system signature needed for detection.
 *  Blocking is separate (see BlockHelper: Shizuku or user settings). */
public final class OpWatcher {
    public interface Listener {
        void onOp(String op, String packageName);
    }

    public static final String OP_AUDIO = AppOpsManager.OPSTR_RECORD_AUDIO;
    public static final String OP_CAMERA = AppOpsManager.OPSTR_CAMERA;
    public static final String OP_FINE = AppOpsManager.OPSTR_FINE_LOCATION;
    public static final String OP_COARSE = AppOpsManager.OPSTR_COARSE_LOCATION;
    public static final String OP_SENSORS = AppOpsManager.OPSTR_BODY_SENSORS;
    public static final String OP_ACTIVITY = AppOpsManager.OPSTR_ACTIVITY_RECOGNITION;
    public static final String OP_SMS = AppOpsManager.OPSTR_READ_SMS;
    public static final String OP_CONTACTS = AppOpsManager.OPSTR_READ_CONTACTS;

    public static final Set<String> WATCHED = new HashSet<>(Arrays.asList(
            OP_AUDIO, OP_CAMERA, OP_FINE, OP_COARSE,
            OP_SENSORS, OP_ACTIVITY, OP_SMS, OP_CONTACTS));

    private OpWatcher() {}

    public static void watch(Context ctx, Listener listener) {
        AppOpsManager ops = (AppOpsManager) ctx.getSystemService(Context.APP_OPS_SERVICE);
        if (ops == null) return;
        for (String op : WATCHED) {
            try {
                // null package = watch this op across all packages
                ops.startWatchingMode(op, null, new AppOpsManager.OnOpChangedListener() {
                    @Override public void onOpChanged(String o, String pkg) {
                        if (pkg == null || pkg.equals(ctx.getPackageName())) return;
                        listener.onOp(o, pkg);
                    }
                });
            } catch (Exception ignored) {
                // op unsupported on this build; keep watching the rest
            }
        }
    }
}
