export const PROTECTED_PATHS = [
  "/dashboard",
  "/tickets",
  "/customers",
  "/establishments",
  "/products",
  "/knowledge",
  "/conversations",
  "/dev/message-simulator"
];

export function isProtectedPath(pathname: string) {
  return PROTECTED_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}
