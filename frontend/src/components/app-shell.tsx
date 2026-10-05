"use client";

import clsx from "clsx";
import { FileText, KanbanSquare, LayoutDashboard, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";
import { relativeDays } from "@/lib/format";

import { Logo } from "./logo";
import { ThemeToggle } from "./theme-toggle";

const NAV = [
  { href: "/board", label: "Board", icon: KanbanSquare },
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/cv", label: "My CV", icon: FileText },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <div className="flex min-h-full flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      {user?.is_demo && (
        <div className="bg-accent-soft px-4 py-1.5 text-center text-xs text-fg">
          You&apos;re exploring a private demo copy — change anything you like.
          {user.demo_expires_at && <> It resets {relativeDays(user.demo_expires_at)}.</>}
        </div>
      )}
      <header className="sticky top-0 z-30 border-b border-border bg-surface/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4">
          <Logo href="/board" />
          <nav aria-label="Main" className="ml-2 hidden items-center gap-1 sm:flex">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={clsx(
                    "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition",
                    active ? "bg-surface-2 text-fg" : "text-fg-muted hover:text-fg",
                  )}
                >
                  <Icon className="size-4" aria-hidden />
                  {label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <span className="hidden max-w-48 truncate text-sm text-fg-muted md:inline">
              {user?.is_demo ? "Demo user" : user?.email}
            </span>
            <ThemeToggle />
            <button
              type="button"
              onClick={() => void logout()}
              className="inline-flex size-9 items-center justify-center rounded-lg text-fg-muted hover:bg-surface-2 hover:text-fg"
              aria-label="Log out"
              title="Log out"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 pb-24 sm:pb-6">
        {children}
      </main>
      {/* Mobile bottom navigation */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-surface sm:hidden"
      >
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={clsx(
                "flex flex-1 flex-col items-center gap-0.5 py-2 text-xs",
                active ? "text-accent" : "text-fg-muted",
              )}
            >
              <Icon className="size-5" aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
