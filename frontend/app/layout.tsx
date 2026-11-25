import type { Metadata, Viewport } from "next";
import "./globals.css";
import TestCopyBanner from "./components/TestCopyBanner";

export const metadata: Metadata = {
  title: "CSP DocMaker — EKO",
  description:
    "CSP Document Generation & Email Automation Platform — Internal EKO Application",
  robots: "noindex, nofollow",
};

/* Phones (No. 176): the page fills the screen around the notch
   (viewport-fit=cover, with the safe areas padded below), and the keyboard
   shrinks the page instead of covering what is being typed. */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0f172a" },
  ],
};

/* Applies the saved theme before the first paint. Without this a returning
   dark-mode user sees a white flash while React hydrates. */
const THEME_SCRIPT = `
try {
  var t = localStorage.getItem('theme');
  if (t === 'dark' || (!t && matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
  }
  var u = localStorage.getItem('uiTheme');
  if (u && /^[a-z]+$/.test(u)) document.documentElement.setAttribute('data-ui-theme', u);
  var st = localStorage.getItem('uiStyle');
  if (st && /^[a-z]+$/.test(st) && st !== 'standard') {
    document.documentElement.setAttribute('data-ui-style', st);
    if (st === 'neon') document.documentElement.classList.add('dark');
  }
  // No. 240: this person's own look (lib/myLook.ts), kept per person.
  var who = JSON.parse(localStorage.getItem('user') || 'null');
  var mine = who && who.email && JSON.parse(localStorage.getItem('myLook:' + String(who.email).toLowerCase()) || 'null');
  if (mine && mine.css) {
    var el = document.createElement('style'); el.id = 'my-look'; el.textContent = mine.css;
    document.head.appendChild(el);
  }
  if (mine && mine.font && String(mine.font).indexOf('https://fonts.googleapis.com/') === 0) {
    var ln = document.createElement('link'); ln.id = 'my-look-font'; ln.rel = 'stylesheet'; ln.href = mine.font;
    document.head.appendChild(ln);
  }
} catch (e) {}
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Font Awesome — the supplied design uses its icons throughout. */}
        <link
          rel="stylesheet"
          href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"
        />
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      {/* Body and container classes are the supplied design's, unchanged. */}
      {/* h-dvh (No. 176): the screen as it is now — a phone's address bar and
          keyboard make 100vh taller than what can be seen. The side safe
          areas keep landscape content clear of the notch. */}
      <body className="font-sans antialiased text-gray-800 bg-gray-50 dark:bg-navy-900 dark:text-gray-200 transition-colors duration-300 min-h-dvh flex flex-col pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
        <div className="flex-grow flex flex-col h-dvh overflow-hidden">
          {children}
        </div>
        {/* Only on a test copy of the app (No. 173). */}
        <TestCopyBanner />
      </body>
    </html>
  );
}
