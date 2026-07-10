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
  title: "GenPicks — NRL predictions",
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
          <nav className="mx-auto flex max-w-4xl items-center gap-6 px-4 py-4">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              GenPicks
            </Link>
            <Link href="/" className="text-sm text-ink-2 hover:text-ink">
              Fixtures
            </Link>
            <Link
              href="/track-record"
              className="text-sm text-ink-2 hover:text-ink"
            >
              Track record
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
            offers. If gambling is a problem for you or someone you know, call
            1800 858 858 (Gambling Help Online).{" "}
            <Link href="/responsible-gambling" className="underline">
              Responsible gambling
            </Link>
          </p>
        </footer>
      </body>
    </html>
  );
}
