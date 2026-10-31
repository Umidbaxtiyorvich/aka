// JARVIS.exe — bitta bosishda JARVIS'ni ochadi.
// O'rnatuvchi uni Windows'dagi .NET Framework kompilyatori (csc.exe) bilan shu kompyuterning o'zida yig'adi.
// Nima qiladi: Ollama ishlamayotgan bo'lsa yoqadi -> JARVIS serveri ishlamayotgan bo'lsa oynasiz ishga tushiradi ->
// tayyor bo'lishini kutadi -> dasturdek alohida oynada (Edge/Chrome --app) ochadi.
// Yangilangandan keyin eski server qolib ketgan bo'lsa (versiyasi diskdagi koddan farq qilsa) — uni to'xtatib, yangisini yoqadi.
// Kalitlar: --no-browser (faqat serverni yoqish, CI uchun), --quiet (xato oynasini ko'rsatmaslik),
//          --update (yangilash oynasini ochadi: scripts\update.ps1 — yorliq bloklangan bo'lsa ham ishlaydi).
// C# 5 (csc v4) bilan mos yozilgan.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Management;
using System.Net;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

static class JarvisLauncher
{
    const string Url = "http://127.0.0.1:8765";
    const string OllamaUrl = "http://127.0.0.1:11434/api/tags";

    static bool Up(string url, int timeoutMs)
    {
        try
        {
            HttpWebRequest r = (HttpWebRequest)WebRequest.Create(url);
            r.Timeout = timeoutMs;
            r.Proxy = null;
            using (HttpWebResponse resp = (HttpWebResponse)r.GetResponse()) { return true; }
        }
        catch (WebException e)
        {
            // HTTP javob (masalan 401) — server ishlayapti degani
            return e.Response != null;
        }
        catch { return false; }
    }

    static string Get(string url, int timeoutMs)
    {
        try
        {
            HttpWebRequest r = (HttpWebRequest)WebRequest.Create(url);
            r.Timeout = timeoutMs;
            r.Proxy = null;
            using (HttpWebResponse resp = (HttpWebResponse)r.GetResponse())
            using (StreamReader sr = new StreamReader(resp.GetResponseStream())) { return sr.ReadToEnd(); }
        }
        catch (WebException e)
        {
            if (e.Response == null) return null;
            using (StreamReader sr = new StreamReader(e.Response.GetResponseStream())) { return sr.ReadToEnd(); }
        }
        catch { return null; }
    }

    static string Field(string text, string pattern)
    {
        Match m = Regex.Match(text ?? "", pattern);
        return m.Success ? m.Groups[1].Value : null;
    }

    // Diskdagi kod versiyasi (jarvis\__init__.py)
    static string LocalVersion(string root)
    {
        try { return Field(File.ReadAllText(Path.Combine(root, @"jarvis\__init__.py")), "__version__\\s*=\\s*\"([^\"]+)\""); }
        catch { return null; }
    }

    // Barcha JARVIS server jarayonlarini to'xtatadi (venv ishga tushiruvchisi ham, uning bola jarayoni — haqiqiy server ham)
    static void StopServers()
    {
        try
        {
            using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name LIKE 'python%'"))
            {
                foreach (ManagementObject o in s.Get())
                {
                    string cl = o["CommandLine"] as string;
                    if (cl == null || cl.IndexOf("jarvis.api", StringComparison.OrdinalIgnoreCase) < 0) continue;
                    try { Process.GetProcessById(Convert.ToInt32(o["ProcessId"])).Kill(); } catch { }
                }
            }
        }
        catch { }
        for (int i = 0; i < 40 && Up(Url + "/api/auth/status", 500); i++) Thread.Sleep(250);
    }

    static void StartHidden(string exe, string args, string dir)
    {
        ProcessStartInfo psi = new ProcessStartInfo(exe, args);
        psi.WorkingDirectory = dir;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.WindowStyle = ProcessWindowStyle.Hidden;
        Process.Start(psi);
    }

    static void EnsureOllama()
    {
        if (Up(OllamaUrl, 800)) return;
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string app = Path.Combine(local, @"Programs\Ollama\ollama app.exe");
        string cli = Path.Combine(local, @"Programs\Ollama\ollama.exe");
        try
        {
            if (File.Exists(app)) Process.Start(app);
            else if (File.Exists(cli)) StartHidden(cli, "serve", local);
        }
        catch { /* Ollama bo'lmasa ham JARVIS ochiladi (offline rejim) */ }
    }

    static string FindAppBrowser()
    {
        string pf86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
        string pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string[] c = {
            Path.Combine(pf86, @"Microsoft\Edge\Application\msedge.exe"),
            Path.Combine(pf, @"Microsoft\Edge\Application\msedge.exe"),
            Path.Combine(pf, @"Google\Chrome\Application\chrome.exe"),
            Path.Combine(pf86, @"Google\Chrome\Application\chrome.exe"),
            Path.Combine(local, @"Google\Chrome\Application\chrome.exe"),
        };
        foreach (string p in c) if (File.Exists(p)) return p;
        return null;
    }

    static void OpenUi()
    {
        string b = FindAppBrowser();
        if (b != null) Process.Start(b, "--app=" + Url + " --window-size=1400,900");
        else Process.Start(Url);
    }

    static string LogTail(string root)
    {
        string log = Path.Combine(root, @"data\logs\server.log");
        if (!File.Exists(log)) return "(server.log topilmadi)";
        try
        {
            string[] lines = File.ReadAllLines(log);
            int from = Math.Max(0, lines.Length - 15);
            return string.Join(Environment.NewLine, lines, from, lines.Length - from);
        }
        catch (Exception e) { return e.Message; }
    }

    [STAThread]
    static int Main(string[] args)
    {
        bool noBrowser = Array.IndexOf(args, "--no-browser") >= 0;
        bool quiet = noBrowser || Array.IndexOf(args, "--quiet") >= 0;
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string pyw = Path.Combine(root, @".venv\Scripts\pythonw.exe");

        if (Array.IndexOf(args, "--update") >= 0)
        {
            string ps = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
            string script = Path.Combine(root, @"scripts\update.ps1");
            if (!File.Exists(script))
            {
                if (!quiet) MessageBox.Show("Yangilash skripti topilmadi:\n" + script, "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 3;
            }
            ProcessStartInfo u = new ProcessStartInfo(ps, "-NoProfile -ExecutionPolicy Bypass -NoExit -File \"" + script + "\"");
            u.WorkingDirectory = root;
            u.UseShellExecute = true;
            Process.Start(u);
            return 0;
        }

        string status = Get(Url + "/api/auth/status", 1500);
        if (status != null)
        {
            string running = Field(status, "\"version\"\\s*:\\s*\"([^\"]+)\"");
            string local = LocalVersion(root);
            if (local == null || running == local)
            {
                if (!noBrowser) OpenUi();
                return 0;
            }
            StopServers();          // eski versiya ishlayapti (yangilanishdan keyin qolib ketgan) — qayta ishga tushiriladi
        }
        if (!File.Exists(pyw))
        {
            if (!quiet) MessageBox.Show("JARVIS o'rnatilmagan yoki .venv buzilgan:\n" + pyw + "\n\nO'rnatuvchini qayta ishga tushiring.", "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }

        Form splash = null;
        if (!quiet)
        {
            splash = new Form();
            splash.FormBorderStyle = FormBorderStyle.None;
            splash.StartPosition = FormStartPosition.CenterScreen;
            splash.Size = new Size(380, 130);
            splash.BackColor = Color.White;
            splash.TopMost = true;
            splash.ShowInTaskbar = true;
            splash.Text = "JARVIS";
            Label t = new Label();
            t.Text = "J.A.R.V.I.S";
            t.Font = new Font("Segoe UI", 18, FontStyle.Bold);
            t.ForeColor = Color.FromArgb(79, 70, 229);
            t.AutoSize = true;
            t.Location = new Point(24, 22);
            Label s = new Label();
            s.Text = "Ishga tushmoqda... (birinchi marta 10-30 soniya)";
            s.Font = new Font("Segoe UI", 10);
            s.ForeColor = Color.FromArgb(100, 116, 139);
            s.AutoSize = true;
            s.Location = new Point(26, 70);
            splash.Controls.Add(t);
            splash.Controls.Add(s);
            splash.Show();
            Application.DoEvents();
        }

        EnsureOllama();
        StartHidden(pyw, "-m jarvis.api --port 8765", root);
        bool ok = false;
        for (int i = 0; i < 180 && !ok; i++)            // 90 soniyagacha kutadi
        {
            Thread.Sleep(500);
            Application.DoEvents();
            ok = Up(Url + "/api/auth/status", 1000);
        }
        if (splash != null) splash.Close();
        if (!ok)
        {
            if (!quiet) MessageBox.Show("JARVIS serveri ishga tushmadi.\n\nOxirgi xabarlar (data\\logs\\server.log):\n\n" + LogTail(root),
                                        "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Error);
            else Console.Error.WriteLine(LogTail(root));
            return 1;
        }
        if (!noBrowser) OpenUi();
        return 0;
    }
}
