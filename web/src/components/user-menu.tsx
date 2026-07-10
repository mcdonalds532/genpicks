import { auth, signIn, signOut } from "@/auth";

// Server component: reads the session per request (all pages are dynamic).
// Sign in/out are server actions posted from plain forms — no client JS.
export async function UserMenu() {
  const session = await auth();

  if (!session?.user) {
    return (
      <form
        className="ml-auto"
        action={async () => {
          "use server";
          await signIn("github");
        }}
      >
        <button
          type="submit"
          className="rounded-md border border-hairline px-3 py-1.5 text-sm text-ink-2 hover:text-ink"
        >
          Sign in with GitHub
        </button>
      </form>
    );
  }

  return (
    <div className="ml-auto flex items-center gap-2.5">
      {session.user.image && (
        // eslint-disable-next-line @next/next/no-img-element -- tiny avatar,
        // not worth routing through the image optimizer
        <img
          src={session.user.image}
          alt=""
          className="h-6 w-6 rounded-full"
        />
      )}
      <span className="hidden text-sm text-ink-2 sm:inline">
        {session.user.name}
      </span>
      <form
        action={async () => {
          "use server";
          await signOut();
        }}
      >
        <button
          type="submit"
          className="text-sm text-muted hover:text-ink"
        >
          Sign out
        </button>
      </form>
    </div>
  );
}
