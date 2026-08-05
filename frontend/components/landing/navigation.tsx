"use client";

import { Menu, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { type Language, useLanguage } from "@/lib/i18n";

function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { language, setLanguage } = useLanguage();

  const options: { code: Language; label: string }[] = [
    { code: "en", label: "EN" },
    { code: "es", label: "ES" },
  ];

  return (
    <div
      aria-label="Language selector"
      className={`inline-flex items-center gap-0.5 rounded-full border border-foreground/15 p-0.5 ${className}`}
      role="group"
    >
      {options.map((option) => (
        <button
          aria-pressed={language === option.code}
          className={`px-3 py-1 text-xs font-mono rounded-full transition-colors duration-300 ${
            language === option.code
              ? "bg-foreground text-background"
              : "text-foreground/60 hover:text-foreground"
          }`}
          key={option.code}
          onClick={() => setLanguage(option.code)}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Navigation() {
  const { t } = useLanguage();
  const [isScrolled, setIsScrolled] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  const navLinks = [
    { name: t.nav.links.features, href: "#features" },
    { name: t.nav.links.howItWorks, href: "#how-it-works" },
    { name: t.nav.links.developers, href: "#developers" },
    { name: t.nav.links.pricing, href: "#pricing" },
  ];

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 20);
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <header
      className={`fixed z-50 transition-all duration-500 ${
        isScrolled ? "top-4 left-4 right-4" : "top-0 left-0 right-0"
      }`}
    >
      <nav
        className={`mx-auto transition-all duration-500 ${
          isScrolled || isMobileMenuOpen
            ? "bg-background/80 backdrop-blur-xl border border-foreground/10 rounded-2xl shadow-lg max-w-[1200px]"
            : "bg-transparent max-w-[1400px]"
        }`}
      >
        <div
          className={`flex items-center justify-between transition-all duration-500 px-6 lg:px-8 ${
            isScrolled ? "h-14" : "h-20"
          }`}
        >
          {/* Logo + Language */}
          <div className="flex items-center gap-3">
            <a className="flex items-center gap-2 group" href="#">
              <span
                className={`font-display tracking-tight transition-all duration-500 ${isScrolled ? "text-xl" : "text-2xl"}`}
              >
                Optimus
              </span>
              <span
                className={`text-muted-foreground font-mono transition-all duration-500 ${isScrolled ? "text-[10px] mt-0.5" : "text-xs mt-1"}`}
              >
                TM
              </span>
            </a>
            <div className="hidden md:block">
              <LanguageSwitcher />
            </div>
          </div>

          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center gap-12">
            {navLinks.map((link) => (
              <a
                className="text-sm text-foreground/70 hover:text-foreground transition-colors duration-300 relative group"
                href={link.href}
                key={link.name}
              >
                {link.name}
                <span className="absolute -bottom-1 left-0 w-0 h-px bg-foreground transition-all duration-300 group-hover:w-full" />
              </a>
            ))}
          </div>

          {/* Desktop CTA */}
          <div className="hidden md:flex items-center gap-4">
            <a
              className={`text-foreground/70 hover:text-foreground transition-all duration-500 ${isScrolled ? "text-xs" : "text-sm"}`}
              href="/login"
            >
              {t.nav.signIn}
            </a>
            <a href="/login">
              <Button
                className={`bg-foreground hover:bg-foreground/90 text-background rounded-full transition-all duration-500 cursor-pointer ${isScrolled ? "px-4 h-8 text-xs" : "px-6"}`}
                size="sm"
              >
                {t.nav.startCreating}
              </Button>
            </a>
          </div>

          {/* Mobile Menu Button */}
          <button
            aria-label={t.nav.toggleMenu}
            className="md:hidden p-2"
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          >
            {isMobileMenuOpen ? (
              <X className="w-6 h-6" />
            ) : (
              <Menu className="w-6 h-6" />
            )}
          </button>
        </div>
      </nav>

      {/* Mobile Menu - Full Screen Overlay */}
      <div
        className={`md:hidden fixed inset-0 bg-background z-40 transition-all duration-500 ${
          isMobileMenuOpen
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none"
        }`}
        style={{ top: 0 }}
      >
        <div className="flex flex-col h-full px-8 pt-28 pb-8">
          {/* Navigation Links */}
          <div className="flex-1 flex flex-col justify-center gap-8">
            {navLinks.map((link, i) => (
              <a
                className={`text-5xl font-display text-foreground hover:text-muted-foreground transition-all duration-500 ${
                  isMobileMenuOpen
                    ? "opacity-100 translate-y-0"
                    : "opacity-0 translate-y-4"
                }`}
                href={link.href}
                key={link.name}
                onClick={() => setIsMobileMenuOpen(false)}
                style={{
                  transitionDelay: isMobileMenuOpen ? `${i * 75}ms` : "0ms",
                }}
              >
                {link.name}
              </a>
            ))}
          </div>

          {/* Bottom CTAs */}
          <div
            className={`flex flex-col gap-4 pt-8 border-t border-foreground/10 transition-all duration-500 ${
              isMobileMenuOpen
                ? "opacity-100 translate-y-0"
                : "opacity-0 translate-y-4"
            }`}
            style={{ transitionDelay: isMobileMenuOpen ? "300ms" : "0ms" }}
          >
            <LanguageSwitcher className="self-center" />
            <div className="flex gap-4">
              <Button
                className="flex-1 rounded-full h-14 text-base"
                onClick={() => {
                  setIsMobileMenuOpen(false);
                  window.location.href = "/login";
                }}
                variant="outline"
              >
                {t.nav.signIn}
              </Button>
              <Button
                className="flex-1 bg-foreground text-background rounded-full h-14 text-base cursor-pointer"
                onClick={() => {
                  setIsMobileMenuOpen(false);
                  window.location.href = "/login";
                }}
              >
                {t.nav.startCreating}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
