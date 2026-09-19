import { NavLink, Outlet } from "react-router";

import { Chip, LogoMark, useAuth } from "@apigw/ui";

import { usePartner } from "./usePartner";

const NAV = [
  { to: "/apis", label: "My APIs" },
  { to: "/sandbox", label: "Sandbox" },
  { to: "/keys", label: "Security keys" },
  { to: "/guides", label: "Guides" },
];

/** Partner-facing chrome (design: DevPortalHome / DevKeys artboards). */
export function Layout() {
  const { signOut } = useAuth();
  const me = usePartner();

  return (
    <div style={{ minHeight: "100%", display: "flex", flexDirection: "column" }}>
      <header style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)" }}>
        <div className="row" style={{ height: 64, padding: "0 30px", gap: 12 }}>
          <div className="row" style={{ gap: 11, marginRight: 14 }}>
            <LogoMark size={30} />
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>Developer Portal</div>
              <div style={{ fontSize: 9.5, letterSpacing: ".09em", textTransform: "uppercase", color: "var(--text-4)" }}>Integration Partners</div>
            </div>
          </div>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} style={({ isActive }) => ({
              height: 63, display: "flex", alignItems: "center", padding: "0 5px", marginRight: 22, fontSize: 13,
              fontWeight: isActive ? 600 : 500, color: isActive ? "var(--text)" : "var(--text-2)", textDecoration: "none",
              whiteSpace: "nowrap",
              borderBottom: `2px solid ${isActive ? "var(--accent)" : "transparent"}`,
            })}>
              {n.label}
            </NavLink>
          ))}
          <div className="grow" />
          {me.data ? (
            <>
              <Chip tone={me.data.accessTier === "PRODUCTION" ? "ok" : "info"}>
                {me.data.accessTier === "PRODUCTION" ? "PRODUCTION + SANDBOX" : "SANDBOX ONLY"}
              </Chip>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{me.data.name}</div>
                <div className="mono" style={{ fontSize: 10, color: "var(--text-4)" }}>{me.data.code}</div>
              </div>
            </>
          ) : null}
          <button className="btn btn-sm" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <main style={{ flex: 1, width: "100%", maxWidth: 1180, margin: "0 auto" }}>
        <Outlet />
      </main>
    </div>
  );
}
