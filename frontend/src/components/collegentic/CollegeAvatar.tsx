import { useState } from "react";
import type { CSSProperties } from "react";
import { cn } from "@/utils";
import type { College } from "@/lib/types";

type Branded = Pick<College, "name" | "logoUrl" | "schoolColors">;

/** Placeholder color for colleges research hasn't found real school colors
 * for yet — always the app's own navy (theme-aware via the CSS variable),
 * not a per-college random pick, so an unresearched college reads as
 * "not found yet" rather than looking like it has a real (if coincidental)
 * brand color. */
const FALLBACK_ACCENT_COLOR = "var(--navy)";

/** A college's real primary brand color if research found one, else the
 * shared placeholder — one accent color per college, used everywhere that
 * wants to color-code by school. */
export function collegeAccentColor(college: Branded): string {
  return college.schoolColors.primary || FALLBACK_ACCENT_COLOR;
}

/** Sets the `--school-accent` CSS variable `.school-tint` (global.css)
 * mixes into a pastel row/card background — spread this onto a `style`
 * prop alongside any other inline styles that element needs. */
export function schoolAccentStyle(college: Branded): CSSProperties {
  return { "--school-accent": collegeAccentColor(college) } as CSSProperties;
}

/** logobrands.com's source images (see requirements_agent.py's
 * _fetch_college_logo) are square canvases with a lot of transparent
 * padding around the mark itself, so at the same object-contain sizing
 * they read visibly smaller than a tightly-cropped Wikipedia seal —
 * zoom just these in so both sources fill the chip similarly. */
function isLogobrandsLogo(url: string): boolean {
  return url.includes("logobrands.com");
}

// 30% larger than a plain h-7/h-9/h-14 chip — logos read too small at the
// original sizing (found live: even the "lg" College Detail header avatar
// still looked cramped next to the school's actual logo proportions).
const SIZE_CLASSES = {
  sm: "h-9 w-9 text-sm",
  md: "h-[47px] w-[47px] text-base",
  lg: "h-[73px] w-[73px] text-xl",
} as const;

/**
 * The school's real logo (Milestone 19: college_research_agent now looks
 * one up) on a neutral white chip — logos are plain PNGs (a white
 * background is fine, no transparency needed) so the chip keeps them
 * legible against any row/card color. Falls back to a colored initial —
 * the school's real primary color if known, else the shared navy
 * placeholder — when there's no logo yet, or its URL fails to load.
 */
export function CollegeAvatar({
  college,
  size = "sm",
}: {
  college: Branded;
  size?: keyof typeof SIZE_CLASSES;
}) {
  const [imgFailed, setImgFailed] = useState(false);

  if (college.logoUrl && !imgFailed) {
    return (
      <span
        className={cn(
          "flex shrink-0 items-center justify-center overflow-hidden rounded-full border-2 bg-white p-1",
          SIZE_CLASSES[size]
        )}
        style={{ borderColor: collegeAccentColor(college) }}
      >
        <img
          src={college.logoUrl}
          alt=""
          className={cn(
            "h-full w-full object-contain",
            isLogobrandsLogo(college.logoUrl) && "scale-[1.8] translate-x-[1px]"
          )}
          onError={() => setImgFailed(true)}
        />
      </span>
    );
  }

  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-semibold text-white",
        SIZE_CLASSES[size]
      )}
      style={{ backgroundColor: collegeAccentColor(college) }}
    >
      {college.name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
