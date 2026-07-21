import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { UserMenu } from "@/components/user-menu";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  // Absolute base for OG/twitter image URLs when pages are shared.
  metadataBase: new URL("https://genpicks.vercel.app"),
  title: "GenPicks — NRL Predictions",
  description:
    "Machine-learning win probabilities and try-scorer markets for the NRL, with implied odds and a public track record.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <header className="border-b border-hairline bg-surface">
          {/* Wraps rather than overflowing: the five items need ~510px of
              run, more than any phone gives us. */}
          <nav className="mx-auto flex max-w-4xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-4 sm:gap-x-6">
            <Link
              href="/"
              className="flex items-center gap-2 text-lg font-semibold tracking-tight"
            >
              {/* The favicon doubles as the wordmark's icon. aria-hidden
                  because "GenPicks" sits right beside it. */}
              {/* eslint-disable-next-line @next/next/no-img-element -- fixed 24px mark, not worth the image optimizer */}
              <img
                src="/icon.svg"
                alt=""
                aria-hidden
                width={24}
                height={24}
                className="h-6 w-6 shrink-0"
              />
              GenPicks
            </Link>
            <Link href="/" className="text-sm text-ink-2 hover:text-ink">
              Fixtures
            </Link>
            <Link
              href="/track-record"
              className="text-sm text-ink-2 hover:text-ink"
            >
              Track Record
            </Link>
            <Link
              href="/methodology"
              className="text-sm text-ink-2 hover:text-ink"
            >
              Methodology
            </Link>
            <UserMenu />
          </nav>
        </header>
        <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">
          {children}
        </main>
        <footer className="border-t border-hairline">
          <p className="mx-auto max-w-4xl px-4 py-4 text-xs text-muted">
            GenPicks is a portfolio project for educational purposes and does
            not provide betting advice. Probabilities are model outputs, not
            offers. Club names and logos are the trademarks of their respective
            clubs and are used here to identify teams; GenPicks is not
            affiliated with, authorised by, or endorsed by the NRL or any club.
            If gambling is a problem for you or someone you know, call
            1800 858 858 (Gambling Help Online).{" "}
            <Link href="/responsible-gambling" className="underline">
              Responsible Gambling
            </Link>
          </p>
        </footer>
      </body>
    </html>
  );
}
