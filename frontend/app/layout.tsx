import type { Metadata } from "next";
import {
  Geist,
  Geist_Mono,
  Instrument_Sans,
  Instrument_Serif,
  JetBrains_Mono,
} from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LanguageProvider } from "@/lib/i18n";

import { Suspense } from "react";
import "./globals.css";
import { ClerkProvider } from "@clerk/nextjs";
import { esES } from "@clerk/localizations";

// Static metadata in the default (es) locale. The client-side LanguageProvider
// updates `document.title` when the user toggles EN/ES, so we avoid reading
// cookies() in generateMetadata (Next 16 "Ambiguous Metadata" error on
// prerenderable routes).
export const metadata: Metadata = {
  metadataBase: new URL("https://chat.vercel.ai"),
  title: "Asistente Fiscal",
  description: "Asistente fiscal basado en el SDK de IA de Next.js.",
};

export const viewport = {
  maximumScale: 1,
};

const geist = Geist({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-geist",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-geist-mono",
});

const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-instrument",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  display: "swap",
  weight: "400",
  variable: "--font-instrument-serif",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains",
});

const LIGHT_THEME_COLOR = "hsl(0 0% 100%)";
const DARK_THEME_COLOR = "hsl(240deg 10% 3.92%)";
const THEME_COLOR_SCRIPT = `\
(function() {
  var html = document.documentElement;
  var meta = document.querySelector('meta[name="theme-color"]');
  if (!meta) {
    meta = document.createElement('meta');
    meta.setAttribute('name', 'theme-color');
    document.head.appendChild(meta);
  }
  function updateThemeColor() {
    var isDark = html.classList.contains('dark');
    meta.setAttribute('content', isDark ? '${DARK_THEME_COLOR}' : '${LIGHT_THEME_COLOR}');
  }
  var observer = new MutationObserver(updateThemeColor);
  observer.observe(html, { attributes: true, attributeFilter: ['class'] });
  updateThemeColor();
})();`;

// Sets <html lang> from the persisted cookie before first paint, so SSR
// stays locale-consistent without reading cookies() in the layout render
// (which would make every route a blocking dynamic route in Next 16).
const LOCALE_SCRIPT = `\
(function() {
  try {
    var m = document.cookie.match(/(?:^|; )optimus-lang=([^;]*)/);
    var lang = m ? decodeURIComponent(m[1]) : '';
    if (lang !== 'en' && lang !== 'es') lang = 'es';
    document.documentElement.lang = lang;
    document.documentElement.setAttribute('data-locale', lang);
  } catch (e) {}
})();`;

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      className={`${geist.variable} ${geistMono.variable} ${instrumentSans.variable} ${instrumentSerif.variable} ${jetbrainsMono.variable}`}
      lang="es"
      suppressHydrationWarning
    >
      <head>
        <script
          suppressHydrationWarning
          // biome-ignore lint/security/noDangerouslySetInnerHtml: "Required"
          dangerouslySetInnerHTML={{
            __html: THEME_COLOR_SCRIPT,
          }}
        />
        <script
          suppressHydrationWarning
          // biome-ignore lint/security/noDangerouslySetInnerHtml: "Required"
          dangerouslySetInnerHTML={{
            __html: LOCALE_SCRIPT,
          }}
        />
      </head>
      <body className="font-sans antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          disableTransitionOnChange
          enableSystem
        >
          <Suspense fallback={null}>
            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
            <ClerkProvider localization={esES as any}>
              <LanguageProvider initialLocale="es">
                <TooltipProvider>{children}</TooltipProvider>
              </LanguageProvider>
            </ClerkProvider>
          </Suspense>
        </ThemeProvider>
      </body>
    </html>
  );
}
