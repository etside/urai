package io.github.tukitattu.urai.cyber;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Scanner;

/** Talks to the Urai backend as the cyberurai-v1 specialist
 *  (tier urai-cyber). No SDK, stdlib-equivalent Java only. */
public final class CyberUraiClient {
    private CyberUraiClient() {}

    public static String analyze(String baseUrl, String key, String pkg, String op) {
        try {
            String task = "Android privacy verdict for package " + pkg
                    + (op != null ? " after " + TrackerDB.opLabel(op) + " access" : "")
                    + ". Reply: RISK low|medium|high, then 3 bullets: why, what data "
                    + "is exposed, what to do. Under 600 chars.";
            JSONObject body = new JSONObject();
            body.put("task", task);
            body.put("tier", "urai-cyber");
            body.put("budget_tokens", 512);
            byte[] data = body.toString().getBytes(StandardCharsets.UTF_8);
            HttpURLConnection c = (HttpURLConnection)
                    new URL(baseUrl.replaceAll("/$", "") + "/agent").openConnection();
            c.setRequestMethod("POST");
            c.setConnectTimeout(20000);
            c.setReadTimeout(280000);
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            if (key != null && !key.isEmpty()) {
                c.setRequestProperty("Authorization", "Bearer " + key);
            }
            c.setRequestProperty("X-Device-Id", "cyberurai-apk");
            try (OutputStream os = c.getOutputStream()) {
                os.write(data);
            }
            String out;
            try (Scanner sc = new Scanner(c.getInputStream(), "UTF-8").useDelimiter("\\A")) {
                out = sc.hasNext() ? sc.next() : "{}";
            }
            JSONObject d = new JSONObject(out);
            String ans = d.optString("answer", "");
            return ans.isEmpty() ? out.substring(0, Math.min(800, out.length())) : ans;
        } catch (Exception e) {
            return "backend unreachable: " + e.getMessage();
        }
    }
}
