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

  // Hover menu with no client JS, to keep this a server component: the
  // panel opens on group-hover and also on group-focus-within, so tabbing
  // to the sign-out button reveals it for keyboard users. That rules out
  // `hidden`/`invisible`, which would drop the button out of the tab order
  // and make focus-within unreachable — hence opacity plus pointer-events.
  //
  // The name always renders (it used to be sm:inline only): it is the
  // menu's trigger now, and a trigger that vanishes on small screens
  // would strand sign-out.
  return (
    <div className="group relative ml-auto">
      <div className="flex cursor-default items-center gap-2.5">
        {session.user.image && (
          // eslint-disable-next-line @next/next/no-img-element -- tiny avatar, not worth the image optimizer
          <img
            src={session.user.image}
            alt=""
            className="h-6 w-6 rounded-full"
          />
        )}
        <span className="text-sm text-ink-2 group-hover:text-ink">
          {session.user.name}
        </span>
      </div>
      {/* pt-2 is the hover bridge: without it the gap between the name and
          the panel counts as leaving the group and the menu shuts. */}
      <div className="pointer-events-none absolute right-0 top-full z-10 pt-2 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
        <form
          action={async () => {
            "use server";
            await signOut();
          }}
        >
          <button
            type="submit"
            className="block w-full whitespace-nowrap rounded-md border border-hairline bg-surface px-3 py-1.5 text-left text-sm text-ink-2 hover:text-ink"
          >
            Sign Out
          </button>
        </form>
      </div>
    </div>
  );
}
