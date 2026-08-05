"use client";

import { ArrowUpRight } from "lucide-react";
import { useLanguage } from "@/lib/i18n";
import { AnimatedWave } from "./animated-wave";

const footerColumns = [
  {
    key: "Product" as const,
    links: [
      { labelKey: "features", href: "#features" },
      { labelKey: "howItWorks", href: "#how-it-works" },
      { labelKey: "pricing", href: "#pricing" },
      { labelKey: "integrations", href: "#integrations" },
    ],
  },
  {
    key: "Developers" as const,
    links: [
      { labelKey: "documentation", href: "#developers" },
      { labelKey: "apiReference", href: "#" },
      { labelKey: "sdk", href: "#developers" },
      { labelKey: "status", href: "#" },
    ],
  },
  {
    key: "Company" as const,
    links: [
      { labelKey: "about", href: "#" },
      { labelKey: "blog", href: "#" },
      { labelKey: "careers", href: "#", badge: true },
      { labelKey: "contact", href: "#" },
    ],
  },
  {
    key: "Legal" as const,
    links: [
      { labelKey: "privacy", href: "#" },
      { labelKey: "terms", href: "#" },
      { labelKey: "security", href: "#security" },
    ],
  },
] as const;

const socialLinks = [
  { name: "Twitter", href: "#" },
  { name: "GitHub", href: "#" },
  { name: "LinkedIn", href: "#" },
];

export function FooterSection() {
  const { t } = useLanguage();

  return (
    <footer className="relative border-t border-foreground/10">
      {/* Animated wave background */}
      <div className="absolute inset-0 h-64 opacity-20 pointer-events-none overflow-hidden">
        <AnimatedWave />
      </div>

      <div className="relative z-10 max-w-[1400px] mx-auto px-6 lg:px-12">
        {/* Main Footer */}
        <div className="py-16 lg:py-24">
          <div className="grid grid-cols-2 md:grid-cols-6 gap-12 lg:gap-8">
            {/* Brand Column */}
            <div className="col-span-2">
              <a className="inline-flex items-center gap-2 mb-6" href="#">
                <span className="text-2xl font-display">Optimus</span>
                <span className="text-xs text-muted-foreground font-mono">
                  TM
                </span>
              </a>

              <p className="text-muted-foreground leading-relaxed mb-8 max-w-xs">
                {t.footer.description}
              </p>

              {/* Social Links */}
              <div className="flex gap-6">
                {socialLinks.map((link) => (
                  <a
                    className="text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 group"
                    href={link.href}
                    key={link.name}
                  >
                    {link.name}
                    <ArrowUpRight className="w-3 h-3 opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all" />
                  </a>
                ))}
              </div>
            </div>

            {/* Link Columns */}
            {footerColumns.map((column) => (
              <div key={column.key}>
                <h3 className="text-sm font-medium mb-6">
                  {t.footer.columns[column.key]}
                </h3>
                <ul className="space-y-4">
                  {column.links.map((link) => (
                    <li key={link.labelKey}>
                      <a
                        className="text-sm text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-2"
                        href={link.href}
                      >
                        {t.footer.links[link.labelKey]}
                        {"badge" in link && link.badge && (
                          <span className="text-xs px-2 py-0.5 bg-foreground text-background rounded-full">
                            {t.footer.hiring}
                          </span>
                        )}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom Bar */}
        <div className="py-8 border-t border-foreground/10 flex flex-col md:flex-row items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">{t.footer.allRights}</p>

          <div className="flex items-center gap-4 text-sm text-muted-foreground">
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              {t.footer.allSystems}
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
