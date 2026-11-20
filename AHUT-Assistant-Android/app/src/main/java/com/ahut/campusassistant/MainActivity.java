package com.ahut.campusassistant;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

public class MainActivity extends Activity {

    private static final int PORT = 8765;
    private static final String LOCAL_URL = "http://127.0.0.1:" + PORT + "/";

    private WebView webView;
    private LinearLayout loading;
    private ProgressBar progress;
    private TextView status;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private volatile String serverError = null;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webview);
        loading = findViewById(R.id.loading);
        progress = findViewById(R.id.progress);
        status = findViewById(R.id.status);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        // 让网页知道当前运行在原生 App 里（用于隐藏 PWA 安装入口）
        settings.setUserAgentString(settings.getUserAgentString() + " AHUTApp/1.0");
        webView.setBackgroundColor(Color.parseColor("#F3F5FB"));
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String url = uri.toString();
                if (url.startsWith("http://127.0.0.1:" + PORT)) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (Exception ignored) {
                }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                loading.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    progress.setVisibility(View.GONE);
                    status.setText("页面加载失败，请退出后重试");
                    loading.setVisibility(View.VISIBLE);
                }
            }
        });

        File webDir = new File(getFilesDir(), "web");
        File dataDir = new File(getFilesDir(), "data");
        try {
            extractWebAssets(webDir);
        } catch (IOException e) {
            status.setText("资源释放失败：" + e.getMessage());
            progress.setVisibility(View.GONE);
            return;
        }

        startServer(webDir, dataDir);
        waitForServer();
    }

    // ---------------- Python 服务 ----------------

    private void startServer(File webDir, File dataDir) {
        final String webPath = webDir.getAbsolutePath();
        final String dataPath = dataDir.getAbsolutePath();
        new Thread(() -> {
            try {
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(getApplicationContext()));
                }
                Python.getInstance()
                        .getModule("android_entry")
                        .callAttr("start", webPath, dataPath, PORT);
            } catch (Throwable t) {
                serverError = t.toString();
            }
        }, "ahut-server").start();
    }

    private void waitForServer() {
        new Thread(() -> {
            long deadline = System.currentTimeMillis() + 120_000L;
            while (System.currentTimeMillis() < deadline) {
                if (serverError != null) {
                    break;
                }
                try (Socket socket = new Socket()) {
                    socket.connect(new InetSocketAddress("127.0.0.1", PORT), 300);
                    handler.post(this::loadApp);
                    return;
                } catch (IOException ignored) {
                    try {
                        Thread.sleep(250);
                    } catch (InterruptedException ignored2) {
                    }
                }
            }
            final String reason = serverError == null ? "启动超时" : serverError;
            handler.post(() -> {
                progress.setVisibility(View.GONE);
                status.setText("服务启动失败：" + reason);
                loading.setVisibility(View.VISIBLE);
            });
        }, "ahut-wait").start();
    }

    private void loadApp() {
        status.setText("正在加载页面…");
        webView.loadUrl(LOCAL_URL);
    }

    // ---------------- web 资源释放 ----------------

    private void extractWebAssets(File webDir) throws IOException {
        String version = readAssetText("web/version.txt");
        File stamp = new File(getFilesDir(), "web.version");
        String oldVersion = stamp.isFile() ? readTextFile(stamp) : "";

        if (webDir.isDirectory() && version.equals(oldVersion)) {
            return;
        }
        deleteRecursive(webDir);
        copyAssetDir("web", webDir);
        try (FileOutputStream out = new FileOutputStream(stamp)) {
            out.write(version.getBytes(StandardCharsets.UTF_8));
        }
    }

    private String readAssetText(String path) throws IOException {
        try (InputStream in = getAssets().open(path)) {
            byte[] buf = new byte[256];
            int n = in.read(buf);
            return n <= 0 ? "" : new String(buf, 0, n, StandardCharsets.UTF_8).trim();
        }
    }

    private String readTextFile(File file) {
        try (InputStream in = new java.io.FileInputStream(file)) {
            byte[] buf = new byte[256];
            int n = in.read(buf);
            return n <= 0 ? "" : new String(buf, 0, n, StandardCharsets.UTF_8).trim();
        } catch (IOException e) {
            return "";
        }
    }

    private void copyAssetDir(String assetPath, File dest) throws IOException {
        String[] children = getAssets().list(assetPath);
        if (children == null || children.length == 0) {
            File parent = dest.getParentFile();
            if (parent != null && !parent.isDirectory()) {
                parent.mkdirs();
            }
            try (InputStream in = getAssets().open(assetPath);
                 OutputStream out = new FileOutputStream(dest)) {
                byte[] buffer = new byte[16384];
                int len;
                while ((len = in.read(buffer)) > 0) {
                    out.write(buffer, 0, len);
                }
            }
            return;
        }
        if (!dest.isDirectory() && !dest.mkdirs()) {
            throw new IOException("无法创建目录：" + dest);
        }
        for (String child : children) {
            copyAssetDir(assetPath + "/" + child, new File(dest, child));
        }
    }

    private void deleteRecursive(File file) {
        if (file == null || !file.exists()) {
            return;
        }
        File[] children = file.listFiles();
        if (children != null) {
            for (File child : children) {
                deleteRecursive(child);
            }
        }
        file.delete();
    }

    // ---------------- 返回键 ----------------

    @Override
    public void onBackPressed() {
        webView.evaluateJavascript(
                "(function(){try{return window.__ahutBack ? window.__ahutBack() : false}catch(e){return false}})()",
                value -> {
                    if (!"true".equals(value)) {
                        if (webView.canGoBack()) {
                            webView.goBack();
                        } else {
                            finish();
                        }
                    }
                });
    }
}
