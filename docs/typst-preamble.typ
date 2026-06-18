// SMACC manual — PDF appearance, layered onto the orange-book Typst template.
//
// Injected via `include-in-header`, which Quarto places AFTER its generated helpers
// (the callout() function, the default `#set table`) and BEFORE `book.with`. So this
// file can redefine callout() and override the table set; page geometry comes from
// _quarto.yml, and heading fonts / running header (owned by book.with, applied after)
// are handled with template-partials in the follow-up PR.

#let smacc-indigo = rgb("#3c48aa")
#let smacc-amber = rgb("#e0b400")
#let smacc-gold = rgb("#b58a00")
#let smacc-amber-ink = rgb("#8a6400")
#let smacc-hairline = rgb("#e3e4ef")
#let smacc-frame = rgb("#d8d8de")
#let smacc-band = rgb("#eef0fb")
#let smacc-zebra = rgb("#f4f5fc")

// ===== Callouts — remap Quarto's per-type colours to the SMACC palette and reshape
// to match the HTML site: rounded, a soft tint fill, a 4pt left accent bar, bold
// title. Quarto passes the type's colour as `icon_color` — note is already indigo
// (via _brand.yml), tip arrives green, warning arrives orange — so remap those two.
#let callout(
  body: [],
  title: "Callout",
  background_color: white,
  icon: none,
  icon_color: black,
  body_background_color: white,
) = {
  let accent = icon_color
  let tint = background_color
  let title-color = icon_color
  if icon_color == rgb("#EB9113") {
    // warning — the focal "can wake a participant" type
    accent = smacc-amber
    tint = smacc-amber.lighten(82%)
    title-color = smacc-amber-ink
  } else if icon_color == rgb("#00A047") {
    // tip
    accent = smacc-gold
    tint = smacc-gold.lighten(82%)
    title-color = smacc-amber-ink
  }
  block(
    width: 100%,
    breakable: true,
    fill: tint,
    radius: 6pt,
    stroke: (left: 4pt + accent),
    inset: 10pt,
  )[
    #block(below: if body != [] { 6pt } else { 0pt })[
      #if icon != none { text(fill: accent, weight: 900)[#icon] + h(6pt) }
      #text(fill: title-color, weight: 700)[#title]
    ]
    #body
  ]
}

// ===== Screenshots — frame each figure's image (rounded, clipped, hairline) so it
// reads as a window, matching the HTML (Typst has no shadow, so the hairline does
// that work). Scoped to the image INSIDE a figure via a nested show rule, so the
// cover logo (rendered by book.with, outside any figure) is untouched and Quarto's
// caption + "Figure N" numbering are preserved.
#show figure.where(kind: "quarto-float-fig"): it => {
  show image: img => box(
    clip: true,
    radius: 6pt,
    stroke: 0.75pt + smacc-frame,
    img,
  )
  it
}

// ===== Tables — a patch sheet: indigo header band with bold Space Grotesk header
// text, faint zebra body, generous insets so long cells wrap. Quarto already emits
// table.header(), which repeats the header across page breaks.
#set table(
  inset: (x: 8pt, y: 6pt),
  stroke: none,
  fill: (x, y) => if y == 0 { smacc-band } else if calc.even(y) { smacc-zebra },
)
#show table.cell.where(y: 0): set text(font: "Space Grotesk", fill: smacc-indigo, weight: 600)
