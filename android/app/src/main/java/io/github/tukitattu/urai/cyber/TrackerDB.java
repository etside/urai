package io.github.tukitattu.urai.cyber;

import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Tracker signatures + permission risk scoring (local database, no network).
 *  Flags ad/analytics SDKs bundled inside apps and dangerous permission sets. */
public final class TrackerDB {
    private static final Map<String, String> TRACKERS = new LinkedHashMap<>();
    static {
        TRACKERS.put("com.facebook.ads", "Meta Audience Network");
        TRACKERS.put("com.facebook.appevents", "Meta App Events");
        TRACKERS.put("com.appsflyer", "AppsFlyer");
        TRACKERS.put("com.adjust", "Adjust");
        TRACKERS.put("com.branch", "Branch Metrics");
        TRACKERS.put("com.onesignal", "OneSignal");
        TRACKERS.put("com.google.android.gms.measurement", "Firebase Analytics");
        TRACKERS.put("com.google.firebase.analytics", "Firebase Analytics");
        TRACKERS.put("com.snapchat.kit", "Snap Kit");
        TRACKERS.put("com.tencent.mm", "WeChat SDK");
        TRACKERS.put("com.umeng", "Umeng");
        TRACKERS.put("io.sentry", "Sentry");
        TRACKERS.put("com.amplitude", "Amplitude");
        TRACKERS.put("com.mixpanel", "Mixpanel");
    }

    private static final Map<String, Integer> RISKY_PERMS = new LinkedHashMap<>();
    static {
        RISKY_PERMS.put("android.permission.RECORD_AUDIO", 30);
        RISKY_PERMS.put("android.permission.CAMERA", 25);
        RISKY_PERMS.put("android.permission.ACCESS_FINE_LOCATION", 25);
        RISKY_PERMS.put("android.permission.ACCESS_BACKGROUND_LOCATION", 30);
        RISKY_PERMS.put("android.permission.READ_SMS", 30);
        RISKY_PERMS.put("android.permission.READ_CONTACTS", 20);
        RISKY_PERMS.put("android.permission.READ_CALL_LOG", 20);
        RISKY_PERMS.put("android.permission.BODY_SENSORS", 20);
        RISKY_PERMS.put("android.permission.ACTIVITY_RECOGNITION", 15);
        RISKY_PERMS.put("android.permission.READ_MEDIA_IMAGES", 10);
        RISKY_PERMS.put("android.permission.ACCESS_MEDIA_LOCATION", 15);
    }

    private TrackerDB() {}

    public static String opLabel(String op) {
        if (op.endsWith("RECORD_AUDIO")) return "microphone";
        if (op.endsWith("CAMERA")) return "camera";
        if (op.contains("LOCATION")) return "location";
        if (op.contains("BODY_SENSORS")) return "body sensors";
        if (op.contains("ACTIVITY_RECOGNITION")) return "activity recognition";
        if (op.contains("READ_SMS")) return "SMS";
        if (op.contains("READ_CONTACTS")) return "contacts";
        return op;
    }

    public static List<String> findTrackers(String[] packages) {
        List<String> out = new ArrayList<>();
        if (packages == null) return out;
        for (String p : packages) {
            String low = p.toLowerCase();
            for (Map.Entry<String, String> e : TRACKERS.entrySet()) {
                if (low.contains(e.getKey())) {
                    out.add(e.getValue() + " (" + p + ")");
                    break;
                }
            }
        }
        return out;
    }

    public static Map<String, Object> score(PackageManager pm, String pkg) {
        Map<String, Object> r = new LinkedHashMap<>();
        List<String> reasons = new ArrayList<>();
        int score = 0;
        try {
            PackageInfo pi = pm.getPackageInfo(pkg, PackageManager.GET_PERMISSIONS);
            if (pi.requestedPermissions != null) {
                for (String perm : pi.requestedPermissions) {
                    Integer w = RISKY_PERMS.get(perm);
                    if (w != null) {
                        score += w;
                        reasons.add(perm.substring(perm.lastIndexOf('.') + 1) + " (+" + w + ")");
                    }
                }
            }
            if (pi.applicationInfo != null && pi.applicationInfo.splitNames != null) {
                for (String t : findTrackers(pi.applicationInfo.splitNames)) {
                    score += 10;
                    reasons.add("tracker: " + t);
                }
            }
        } catch (Exception e) {
            reasons.add("query failed: " + e.getMessage());
        }
        r.put("score", Math.min(100, score));
        r.put("reasons", reasons);
        return r;
    }
}
