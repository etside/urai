package io.github.tukitattu.urai.cyberguard;

import android.content.Context;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/**
 * CyberGuard threat intel cache for Android.
 * Loads IOC feeds from the Urai server and local assets.
 * Updated daily in background.
 */
public class ThreatIntel {
    private final Set<String> blockedIps   = Collections.synchronizedSet(new HashSet<>());
    private final Set<String> maliciousDomains = Collections.synchronizedSet(new HashSet<>());

    // TraderTraitor / Lazarus / APT known IPs (static seed, updated via server)
    private static final String[] SEED_IPS = {
        // North Korea TraderTraitor known egress (public threat intel)
        "175.45.178.0","210.52.109.0","77.83.196.0",
        // Lazarus Group infrastructure samples
        "195.123.220.0","194.165.16.0",
    };

    // Known C2 domain patterns (seed list)
    private static final String[] SEED_DOMAINS = {
        "coinsupportservice.com","blockchainsecure.net","cryptoverifyapp.com",
        "defi-support.xyz","wallet-verify.net","nft-claim.io",
    };

    public ThreatIntel() {
        Collections.addAll(blockedIps, SEED_IPS);
        Collections.addAll(maliciousDomains, SEED_DOMAINS);
    }

    public void loadFromUraiServer(String baseUrl, String apiKey) {
        new Thread(() -> {
            try {
                HttpURLConnection c = (HttpURLConnection)
                    new URL(baseUrl.replaceAll("/$","") + "/v1/threat/intel").openConnection();
                c.setConnectTimeout(10000);
                c.setReadTimeout(10000);
                if (apiKey != null && !apiKey.isEmpty())
                    c.setRequestProperty("Authorization", "Bearer " + apiKey);
                try (BufferedReader r = new BufferedReader(
                        new InputStreamReader(c.getInputStream()))) {
                    StringBuilder sb = new StringBuilder();
                    String line;
                    while ((line = r.readLine()) != null) sb.append(line);
                    // Parse JSON: {"ioc_ips":[...],"ioc_domains":[...]}
                    parseJsonLists(sb.toString());
                }
            } catch (Exception ignored) {}
        }).start();
    }

    private void parseJsonLists(String json) {
        // Minimal JSON parser for string arrays
        String ips = extractArray(json, "ioc_ips");
        String domains = extractArray(json, "ioc_domains");
        for (String ip : ips.split(",")) {
            String clean = ip.trim().replaceAll("["\[\]]","");
            if (!clean.isEmpty()) blockedIps.add(clean);
        }
        for (String d : domains.split(",")) {
            String clean = d.trim().replaceAll("["\[\]]","");
            if (!clean.isEmpty()) maliciousDomains.add(clean.toLowerCase());
        }
    }

    private String extractArray(String json, String key) {
        int idx = json.indexOf("\"" + key + "\"");
        if (idx < 0) return "";
        int start = json.indexOf("[", idx);
        int end = json.indexOf("]", start);
        if (start < 0 || end < 0) return "";
        return json.substring(start + 1, end);
    }

    public boolean isBlockedIp(String ip) {
        return blockedIps.contains(ip);
    }

    public boolean isMaliciousDomain(String domain) {
        if (domain == null) return false;
        String d = domain.toLowerCase();
        if (maliciousDomains.contains(d)) return true;
        // Check suffix match
        for (String bad : maliciousDomains) {
            if (d.endsWith("." + bad) || d.equals(bad)) return true;
        }
        return false;
    }

    public void addBlockedIp(String ip) { blockedIps.add(ip); }
    public void removeBlockedIp(String ip) { blockedIps.remove(ip); }
    public Set<String> getBlockedIps() { return Collections.unmodifiableSet(blockedIps); }
}
