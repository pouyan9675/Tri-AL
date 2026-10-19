import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { LayoutDashboard, Orbit, SearchIcon, Settings2, TableProperties } from "lucide-react";
import { useMemo } from "react";
import { metaQuery } from "@/api/queries";
import { Logo } from "@/components/logo";
import { Kbd } from "@/components/ui/kbd";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";
import { formatNumber } from "@/lib/format";
import { isActive } from "@/lib/live";
import { useLive } from "@/lib/live-context";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { to: "/analysis", label: "Analysis", icon: Orbit, exact: false },
  { to: "/trials", label: "Trials", icon: TableProperties, exact: false },
] as const;

export function AppSidebar({
  onSearch,
  onSearchIntent,
}: {
  onSearch: () => void;
  onSearchIntent: () => void;
}) {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const { setOpenMobile } = useSidebar();
  const jobs = useLive((state) => state.jobs);
  const running = useMemo(() => Object.values(jobs).find(isActive), [jobs]);

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader className="h-14 justify-center">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              asChild
              className="hover:bg-transparent active:bg-transparent"
            >
              <Link to="/" onClick={() => setOpenMobile(false)}>
                <Logo className="size-8" />
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate font-semibold tracking-tight">Tri-AL</span>
                  <span className="truncate text-xs text-muted-foreground">
                    Clinical trials, locally
                  </span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Explore</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => {
                const active = item.exact
                  ? pathname === item.to
                  : pathname === item.to || pathname.startsWith(`${item.to}/`);
                return (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton asChild isActive={active} tooltip={item.label}>
                      <Link to={item.to} onClick={() => setOpenMobile(false)}>
                        <item.icon />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
              <SidebarMenuItem>
                <SidebarMenuButton
                  tooltip="Search"
                  onClick={() => {
                    setOpenMobile(false);
                    onSearch();
                  }}
                  onPointerEnter={onSearchIntent}
                >
                  <SearchIcon />
                  <span>Search</span>
                </SidebarMenuButton>
                <SidebarMenuBadge>
                  <Kbd className="h-5 text-[0.65rem]">⌘K</Kbd>
                </SidebarMenuBadge>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>System</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  asChild
                  isActive={pathname === "/settings"}
                  tooltip={running ? `Settings: ${running.type} running` : "Settings"}
                >
                  <Link to="/settings" onClick={() => setOpenMobile(false)}>
                    <Settings2 />
                    <span>Settings</span>
                  </Link>
                </SidebarMenuButton>
                {running && (
                  <SidebarMenuBadge>
                    <Spinner className="size-3.5 text-brand" />
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <LiveFooter />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

function LiveFooter() {
  const status = useLive((state) => state.status);
  const { data: meta } = useQuery(metaQuery());
  const label = status === "open" ? "Live" : status === "connecting" ? "Connecting…" : "Offline";
  return (
    <div className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-xs group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
      <span className="relative flex size-2 shrink-0" title={label}>
        {status === "open" && (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-good opacity-40 [animation-duration:2.5s]" />
        )}
        <span
          className={cn(
            "relative inline-flex size-2 rounded-full",
            status === "open"
              ? "bg-good"
              : status === "connecting"
                ? "bg-warning"
                : "bg-muted-foreground/50",
          )}
        />
      </span>
      <div className="grid min-w-0 leading-tight group-data-[collapsible=icon]:hidden">
        <span className="font-medium">{label}</span>
        <span className="truncate text-muted-foreground">
          {meta ? `${formatNumber(meta.trials)} trials · v${meta.version}` : "Tri-AL"}
        </span>
      </div>
    </div>
  );
}
