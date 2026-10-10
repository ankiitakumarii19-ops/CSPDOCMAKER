import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CSP DocMaker — EKO",
  description:
    "CSP Document Generation & Email Automation Platform — Internal EKO Application",
  robots: "noindex, nofollow",
};

/* Applies the saved theme before the first paint. Without this a returning
   dark-mode user sees a white flash while React hydrates. */
const THEME_SCRIPT = `
try {
  var t = localStorage.getItem('theme');
  if (t === 'dark' || (!t && matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
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
      <body className="font-sans antialiased text-gray-800 bg-gray-50 dark:bg-navy-900 dark:text-gray-200 transition-colors duration-300 min-h-screen flex flex-col">
        <div className="flex-grow flex flex-col h-screen overflow-hidden">
          {children}
        </div>
      </body>
    </html>
  );
}
