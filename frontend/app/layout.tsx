import type { Metadata } from "next";
import {
  Geist,
  Geist_Mono,
  Instrument_Sans,
  Instrument_Serif,
  JetBrains_Mono,
} from "next/font/google";
import { Suspense } from "react";
import { ClerkLocaleProvider } from "@/components/auth/clerk-locale-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LanguageProvider } from "@/lib/i18n";
import "./globals.css";

// Static metadata in the default (es) locale. The client-side LanguageProvider
// updates `document.title` when the user toggles EN/ES, so we avoid reading
// cookies() in generateMetadata (Next 16 "Ambiguous Metadata" error on
// prerenderable routes).
export const metadata: Metadata = {
  metadataBase: new URL("https://chat.vercel.ai"),
  title: "Agente Fiscal",
  description: "Agente fiscal basado en el SDK de IA de Next.js.",
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

// Spanish is the only supported language. Force <html lang> to "es" before
// first paint, ignoring any legacy optimus-lang cookie.
const LOCALE_SCRIPT = `\
(function() {
  try {
    document.documentElement.lang = 'es';
    document.documentElement.setAttribute('data-locale', 'es');
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
          // biome-ignore lint/security/noDangerouslySetInnerHtml: "Required"
          dangerouslySetInnerHTML={{
            __html: THEME_COLOR_SCRIPT,
          }}
          suppressHydrationWarning
        />
        <script
          // biome-ignore lint/security/noDangerouslySetInnerHtml: "Required"
          dangerouslySetInnerHTML={{
            __html: LOCALE_SCRIPT,
          }}
          suppressHydrationWarning
        />
      </head>
      <body className="font-sans antialiased">
        <Suspense fallback={null}>
          <LanguageProvider initialLocale="es">
            <ClerkLocaleProvider>
              <TooltipProvider>{children}</TooltipProvider>
            </ClerkLocaleProvider>
          </LanguageProvider>
        </Suspense>
      </body>
    </html>
  );
}
