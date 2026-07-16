import { NextRequest, NextResponse } from "next/server";
import { ACCESS_TOKEN_KEY } from "@/lib/auth";
import { isProtectedPath } from "@/lib/routes";

export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname === "/login" && request.cookies.get(ACCESS_TOKEN_KEY)?.value) {
    const dashboardUrl = request.nextUrl.clone();
    dashboardUrl.pathname = "/dashboard";
    dashboardUrl.search = "";
    return NextResponse.redirect(dashboardUrl);
  }

  if (!isProtectedPath(request.nextUrl.pathname)) {
    return NextResponse.next();
  }

  const token = request.cookies.get(ACCESS_TOKEN_KEY)?.value;
  if (token) {
    return NextResponse.next();
  }

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/login", "/dashboard/:path*", "/tickets/:path*", "/customers/:path*", "/establishments/:path*", "/products/:path*", "/knowledge/:path*", "/conversations/:path*", "/dev/message-simulator/:path*"]
};
