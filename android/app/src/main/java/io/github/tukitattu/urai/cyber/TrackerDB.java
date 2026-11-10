package io.github.tukitattu.urai.cyber;

import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Tracker signatures + permission risk scoring (local database, no network).
 *  Detects ad/analytics SDKs actually bundled inside an APK by scanning its
 *  dex string pools, and scores only the permissions the app was *granted*. */
public final class TrackerDB {
    private static final Map<String, String> TRACKERS = new LinkedHashMap<>();
    static {
        TRACKERS.put("com.google.android.gms.ads", "Google Mobile Ads");
        TRACKERS.put("com.google.android.gms.analytics", "Google Analytics");
        TRACKERS.put("com.google.android.gms.measurement", "Firebase Analytics");
        TRACKERS.put("com.google.firebase.analytics", "Firebase Analytics");
        TRACKERS.put("com.google.firebase.crashlytics", "Firebase Crashlytics");
        TRACKERS.put("com.crashlytics", "Crashlytics");
        TRACKERS.put("com.facebook.ads", "Meta Audience Network");
        TRACKERS.put("com.facebook.appevents", "Meta App Events");
        TRACKERS.put("com.facebook.login", "Facebook Login");
        TRACKERS.put("com.adjust", "Adjust");
        TRACKERS.put("com.appsflyer", "AppsFlyer");
        TRACKERS.put("com.flurry", "Flurry");
        TRACKERS.put("com.mopub", "MoPub");
        TRACKERS.put("com.unity3d.ads", "Unity Ads");
        TRACKERS.put("com.unity3d.services", "Unity Services");
        TRACKERS.put("com.onesignal", "OneSignal");
        TRACKERS.put("com.branch", "Branch Metrics");
        TRACKERS.put("io.branch", "Branch Metrics");
        TRACKERS.put("com.amplitude", "Amplitude");
        TRACKERS.put("com.mixpanel", "Mixpanel");
        TRACKERS.put("io.sentry", "Sentry");
        TRACKERS.put("com.snapchat.kit", "Snap Kit");
        TRACKERS.put("com.tencent.mm", "WeChat SDK");
        TRACKERS.put("com.umeng", "Umeng");
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

    private static final int MAX_WINDOW = 64;                 // longest signature overlap
    private static final long MAX_DEX_BYTES = 96L * 1024 * 1024;

    // Detection reads every dex of every installed app; cache per package.
    private static final Map<String, List<String>> DETECT_CACHE = new LinkedHashMap<>();

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

    /** Names of tracker SDKs whose class prefixes are present in the APK(s). */
    public static List<String> detectTrackers(PackageManager pm, String pkg) {
        synchronized (DETECT_CACHE) {
            List<String> cached = DETECT_CACHE.get(pkg);
            if (cached != null) return cached;
        }
        List<String> found = new ArrayList<>();
        try {
            ApplicationInfo ai = pm.getApplicationInfo(pkg, 0);
            if (ai.sourceDir != null) scanApk(ai.sourceDir, found);
            if (ai.splitSourceDirs != null) {
                for (String split : ai.splitSourceDirs) {
                    if (split != null) scanApk(split, found);
                }
            }
        } catch (Throwable t) {
            // Unreadable/instant app: report nothing rather than crash the scan.
        }
        synchronized (DETECT_CACHE) {
            DETECT_CACHE.put(pkg, found);
        }
        return found;
    }

    private static void scanApk(String path, List<String> found) {
        File f = new File(path);
        if (!f.isFile() || !f.canRead()) return;
        ZipFile zip = null;
        try {
            zip = new ZipFile(f);
            Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry e = entries.nextElement();
                if (e == null) continue;
                String name = e.getName();
                if (name != null) match(name, found);
                // Class prefixes live in the dex string table; entry names only
                // catch assets/resources. Read the dex bytes and search them.
                if (name != null && name.endsWith(".dex")) {
                    long size = e.getSize();
                    if (size <= 0 || size <= MAX_DEX_BYTES) scanDex(zip, e, found);
                }
                if (found.size() >= TRACKERS.size()) return;
            }
        } catch (Throwable t) {
            // Corrupt or encrypted split; skip it.
        } finally {
            if (zip != null) {
                try {
                    zip.close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private static void scanDex(ZipFile zip, ZipEntry e, List<String> found) {
        InputStream in = null;
        try {
            in = zip.getInputStream(e);
            byte[] buf = new byte[64 * 1024];
            String tail = "";
            int n;
            while ((n = in.read(buf)) > 0) {
                String window = tail + new String(buf, 0, n, StandardCharsets.ISO_8859_1);
                match(window, found);
                if (found.size() >= TRACKERS.size()) return;
                if (window.length() > MAX_WINDOW) {
                    tail = window.substring(window.length() - MAX_WINDOW);
                } else {
                    tail = window;
                }
            }
        } catch (Throwable t) {
            // Truncated dex; keep whatever we matched so far.
        } finally {
            if (in != null) {
                try {
                    in.close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private static void match(String haystack, List<String> found) {
        if (haystack == null || haystack.isEmpty()) return;
        // Dex stores class names as type descriptors with '/' separators
        // (e.g. Lcom/google/android/gms/ads/AdView;), so normalise slashes to
        // dots before comparing against the dotted tracker package prefixes.
        String low = haystack.toLowerCase(Locale.US).replace('/', '.');
        for (Map.Entry<String, String> e : TRACKERS.entrySet()) {
            if (low.contains(e.getKey()) && !found.contains(e.getValue())) {
                found.add(e.getValue());
            }
        }
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
                    if (w == null) continue;
                    // Only count permissions the package actually holds.
                    boolean granted;
                    try {
                        granted = pm.checkPermission(perm, pkg)
                                == PackageManager.PERMISSION_GRANTED;
                    } catch (Exception ex) {
                        granted = false;
                    }
                    if (!granted) continue;
                    score += w;
                    reasons.add(perm.substring(perm.lastIndexOf('.') + 1) + " (+" + w + ")");
                }
            }
            for (String tracker : detectTrackers(pm, pkg)) {
                score += 10;
                reasons.add("bundled tracker: " + tracker);
            }
        } catch (Exception e) {
            reasons.add("query failed: " + e.getMessage());
        }
        r.put("score", Math.min(100, score));
        r.put("reasons", reasons);
        return r;
    }
}
