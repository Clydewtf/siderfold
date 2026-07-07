<design_plan>
Python RNG Execution:
seed = len("aggregator-site-mvp-dashboard-catalog") % 997 = 37
hero = random.choice(["Cinematic Center", "Artistic Asymmetry", "Editorial Split"]) -> "Editorial Split"
font = random.choice(["Satoshi", "Cabinet Grotesk", "Outfit", "Geist"]) -> "Geist"
components = ["Inline Typography Images", "Horizontal Accordions", "Infinite Marquee"]
gsap = ["Scroll Pinning (GSAP Split)", "Image Scale & Fade Scroll"]

AIDA Check:
Navigation exists as compact premium tab shell. Attention is the Home hero. Interest is the metrics and bento dashboard. Desire is a pinned analytics/media section and scale/fade cards. Action is a high-contrast footer/status band that routes to Sources and All Programs.

Hero Math Verification:
H1 uses max-w-6xl with clamp(3rem,5vw,5.5rem), wide split layout, and short Russian copy so it stays within 2-3 lines. No stamp icons, spam tags, or raw stats appear inside the hero.

Bento Density Verification:
Home bento uses md:grid-cols-6 with exactly 12 occupied cells: main card col-span-3 row-span-2 = 6, two side cards col-span-3 row-span-1 = 6 total. grid-flow-dense is applied and no dead cells remain.

Label Sweep & Button Check:
No labels such as SECTION 01, QUESTION 05, or ABOUT US are used. Primary buttons render white text on ink background; secondary buttons render ink text on light background with visible borders.
</design_plan>
