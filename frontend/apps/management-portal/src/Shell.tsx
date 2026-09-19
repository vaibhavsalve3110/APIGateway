import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router";

import { LogoMark, useAuth } from "@apigw/ui";

import "./shell.css";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  adminOnly?: boolean;
  planned?: boolean;
}

const icon = (d: string) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const sections: { title: string; items: NavItem[] }[] = [
  { title: "Overview", items: [{ to: "/dashboard", label: "Dashboard", icon: icon("M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"), planned: true }] },
  {
    title: "API Management",
    items: [
      { to: "/apis", label: "APIs", icon: icon("M12 3 3 7.5 12 12l9-4.5L12 3ZM3 12l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5") },
      { to: "/products", label: "Products", icon: icon("M21 8v8l-9 5-9-5V8l9-5 9 5ZM3 8l9 5 9-5"), planned: true, adminOnly: true },
    ],
  },
  {
    title: "Partners",
    items: [
      { to: "/partners", label: "Groups & Partners", icon: icon("M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 4.3a3.2 3.2 0 1 1 0 6.4 3.2 3.2 0 0 1 0-6.4"), adminOnly: true },
      { to: "/mapping", label: "Access Mapping", icon: icon("m9 11 3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"), planned: true, adminOnly: true },
      { to: "/domains", label: "Domains", icon: icon("M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"), planned: true, adminOnly: true },
    ],
  },
  {
    title: "Reporting & Security",
    items: [
      { to: "/usage", label: "API Usage", icon: icon("M3 3v18h18M7 15l3.5-4 3 2.5L20 7") },
      { to: "/audit", label: "Audit Log", icon: icon("M12 2 4 5.5v6c0 5 3.4 9 8 10.5 4.6-1.5 8-5.5 8-10.5v-6L12 2Z"), adminOnly: true },
      { to: "/users", label: "Users & Roles", icon: icon("M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"), planned: true, adminOnly: true },
    ],
  },
];

export function Shell() {
  const { user, signOut } = useAuth();
  const isAdmin = user.roles.includes("ADMIN");
  const initials = user.username.slice(0, 2).toUpperCase();

  return (
    <div className="shell">
      <nav className="rail">
        <div className="rail-brand">
          <LogoMark />
          <div>
            <div className="rail-title">API Gateway</div>
            <div className="rail-sub">Management Portal</div>
          </div>
        </div>
        <div className="rail-scroll">
          {sections.map((section) => {
            const items = section.items.filter((i) => isAdmin || !i.adminOnly);
            if (items.length === 0) {
              return null;
            }
            return (
              <div key={section.title}>
                <div className="rail-section">{section.title}</div>
                {items.map((item) => (
                  <NavLink key={item.to} to={item.to} className={({ isActive }) => `rail-item${isActive ? " active" : ""}`}>
                    {item.icon}
                    <span className="grow">{item.label}</span>
                    {item.planned ? <span className="rail-planned">soon</span> : null}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </div>
        <div className="rail-user">
          <div className="rail-avatar">{initials}</div>
          <div className="grow">
            <div className="rail-user-name">{user.username}</div>
            <div className="rail-sub">{user.roles.join(", ").toLowerCase()}</div>
          </div>
          <button className="rail-signout" onClick={signOut} title="Sign out" aria-label="Sign out">
            {icon("M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9")}
          </button>
        </div>
      </nav>
      <main className="shell-main">
        <Outlet />
      </main>
    </div>
  );
}
