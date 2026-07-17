// Auth.js (next-auth v5) with GitHub OAuth and stateless JWT sessions.
//
// The Postgres schema is owned by the FastAPI side (Alembic), so there is
// no database adapter here: on sign-in the user is synced into the API's
// users table over an internal shared-key endpoint, and our DB user id is
// carried in the JWT. That id is what the API checks subscriptions against.

import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import { cache } from "react";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

declare module "next-auth" {
  interface Session {
    // "userId" would intersect with Auth.js's AdapterSession.userId
    // (a string) and collapse to never — hence the prefixed name.
    /** GenPicks users.id, null if the sync hasn't succeeded yet. */
    genpicksUserId: number | null;
  }
}

type SyncInput = {
  github_id: string;
  email: string | null;
  name: string | null;
  avatar_url: string | null;
};

async function syncUser(input: SyncInput): Promise<number | null> {
  try {
    const res = await fetch(`${API_URL}/internal/users/sync`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Internal-Key": process.env.GENPICKS_INTERNAL_API_KEY ?? "",
      },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return ((await res.json()) as { user_id: number }).user_id;
  } catch {
    return null; // API asleep/unreachable: retried on the next request
  }
}

const nextAuth = NextAuth({
  providers: [GitHub],
  session: { strategy: "jwt" },
  callbacks: {
    async jwt({ token, profile }) {
      if (profile) {
        // initial sign-in: the GitHub profile is only present here
        token.genpicksUserId = await syncUser({
          github_id: String(profile.id),
          email: profile.email ?? null,
          name: (profile.name ?? profile.login ?? null) as string | null,
          avatar_url: (profile.avatar_url ?? null) as string | null,
        });
      } else if (token.genpicksUserId == null && token.sub) {
        // sign-in sync failed (e.g. API cold start): retry from token claims
        token.genpicksUserId = await syncUser({
          github_id: token.sub,
          email: token.email ?? null,
          name: token.name ?? null,
          avatar_url: (token.picture as string | null) ?? null,
        });
      }
      return token;
    },
    session({ session, token }) {
      session.genpicksUserId = (token.genpicksUserId as number | null) ?? null;
      return session;
    },
  },
});

export const { handlers, signIn, signOut } = nextAuth;

// generateMetadata and the page body both read the session on a match
// view; without cache() each call decodes the JWT again and — while a
// user's sign-in sync is still failing — repeats the syncUser POST.
export const auth: typeof nextAuth.auth = cache(nextAuth.auth);
