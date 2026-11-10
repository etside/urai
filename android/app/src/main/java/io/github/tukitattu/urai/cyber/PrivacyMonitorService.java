package io.github.tukitattu.urai.cyber;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

import java.util.HashMap;
import java.util.Map;

/** Foreground service: watches sensor/data ops, correlates with the
 *  foreground app, notifies on background/suspicious access. Detection is
 *  passive (no system rights needed); blocking happens on user tap
 *  (see BlockHelper). */
public class PrivacyMonitorService extends Service {
    public static final String CH = "cyberurai-watch";
    private static final int FG_ID = 1001;
    private final Map<String, Long> lastAlert = new HashMap<>();

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm != null) {
            nm.createNotificationChannel(new NotificationChannel(
                    CH, "CyberUrai monitor", NotificationManager.IMPORTANCE_LOW));
        }
        Notification.Builder b = (Build.VERSION.SDK_INT >= 26)
                ? new Notification.Builder(this, CH)
                : new Notification.Builder(this);
        b.setContentTitle("CyberUrai watching")
         .setContentText("Monitoring mic, camera, location and sensor access")
         .setSmallIcon(android.R.drawable.ic_lock_idle_lock);
        startForeground(FG_ID, b.build());

        OpWatcher.watch(this, (op, pkg) -> onAccess(op, pkg));
    }

    private void onAccess(String op, String pkg) {
        long now = System.currentTimeMillis();
        Long last = lastAlert.get(op + "|" + pkg);
        if (last != null && now - last < 60_000) return; // one alert/min per op+pkg
        lastAlert.put(op + "|" + pkg, now);
        String fg = foregroundPackage();
        boolean background = fg != null && !fg.equals(pkg);
        String label = TrackerDB.opLabel(op);
        String text = pkg + " used " + label + (background ? " while in background" : "");
        Intent i = new Intent(this, CyberActivity.class)
                .putExtra("pkg", pkg).putExtra("op", op)
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pi = PendingIntent.getActivity(this, (pkg + op).hashCode(), i,
                PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23
                        ? PendingIntent.FLAG_IMMUTABLE : 0));
        Notification.Builder b = (Build.VERSION.SDK_INT >= 26)
                ? new Notification.Builder(this, CH)
                : new Notification.Builder(this);
        b.setContentTitle("Hidden access? " + label)
         .setContentText(text + " — tap to review/block")
         .setSmallIcon(android.R.drawable.ic_dialog_alert)
         .setContentIntent(pi).setAutoCancel(true);
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm != null) nm.notify((pkg + op + now).hashCode(), b.build());
    }

    private String foregroundPackage() {
        try {
            UsageStatsManager usm = (UsageStatsManager) getSystemService(Context.USAGE_STATS_SERVICE);
            if (usm == null) return null;
            long end = System.currentTimeMillis();
            UsageEvents ev = usm.queryEvents(end - 30_000, end);
            UsageEvents.Event e = new UsageEvents.Event();
            String last = null;
            while (ev != null && ev.hasNextEvent()) {
                ev.getNextEvent(e);
                if (e.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND) {
                    last = e.getPackageName();
                }
            }
            return last;
        } catch (Exception ex) {
            return null;
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
