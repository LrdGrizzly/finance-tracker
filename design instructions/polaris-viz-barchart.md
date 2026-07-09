# Polaris Viz — BarChart Design Reference

Source: [polaris-viz.shopify.dev](https://polaris-viz.shopify.dev/) documentation (Legends, Data Structure, Labels, Hooks, BarChart).

---

## 📓 Legends

The more data series in a chart, the more colors and shapes it has, making it harder to parse quickly. Interactive legends let users highlight individual series to parse information another way, and help distinguish series for people with color vision deficiencies.

Legends respond to hover and focus events to highlight the corresponding series on the chart.

**Guidelines**

- Legends are not available on SparkCharts.
- Legends should always be used on charts with more than one series.

**How legends are generated**

Legend `title` and `color` are generated from the root `name` property of each provided `DataSeries`.

```tsx
const DATA = [
  {
    name: 'Breakfast',
    data: [...],
  },
  {
    name: 'Lunch',
    color: 'green',
    data: [...],
  },
  {
    name: 'Dinner',
    data: [...],
  },
];
```

---

## 🧪 Data Structure

All Polaris Viz charts have a `data` prop that accepts an array of `DataSeries` or `DataGroup`.

```tsx
interface DataSeries {
  data: DataPoint[];
  color?: Color;
  isComparison?: boolean;
  name?: string;
}
```

```tsx
interface DataGroup {
  shape: Shape;
  series: DataSeries[];
  yAxisOptions?: YAxisOptions[];
}
```

### `DataSeries.data`

Accepts an array of `DataPoint`:

```tsx
interface DataPoint {
  key: number | string;
  value: number | null;
}
```

**Example** — comparing shark species size as they grow:

- `DataSeries.name` — the shark species name
- `DataPoint.key` — the shark's age in years
- `DataPoint.value` — the shark's size in cm at that age

```tsx
export const SHARK_SPECIES_GROWTH = [
  {
    name: 'Mako',
    data: [
      { key: '0', value: 80 },
      { key: '5', value: 170 },
      { key: '10', value: 210 },
      { key: '15', value: 240 },
    ],
  },
  {
    name: 'Great White',
    data: [
      { key: '0', value: 80 },
      { key: '5', value: 180 },
      { key: '10', value: 250 },
      { key: '15', value: 350 },
    ],
  },
];
```

The same data set can drive different chart types:

```jsx
<BarChart
  xAxisOptions={{ labelFormatter: (x) => `${x} years old` }}
  yAxisOptions={{ labelFormatter: (y) => `${y} cm` }}
  data={SHARK_SPECIES_GROWTH}
/>
```

```jsx
<LineChart
  xAxisOptions={{ labelFormatter: (x) => `${x} years old` }}
  yAxisOptions={{ labelFormatter: (y) => `${y} cm` }}
  data={SHARK_SPECIES_GROWTH}
/>
```

### `DataSeries.color`

Overwrites the theme's series color for that series.

```jsx
<BarChart
  data={[
    { ...SHARK_SPECIES_GROWTH[0], color: 'lime' },
    SHARK_SPECIES_GROWTH[1],
  ]}
/>
```

### `DataSeries.isComparison`

If `true`, the chart uses default comparison-series styling — gray bars, gray dashed lines.

```jsx
<BarChart
  data={[
    { ...SHARK_SPECIES_GROWTH[0], isComparison: true },
    SHARK_SPECIES_GROWTH[1],
  ]}
/>
```

### Filling data

When multiple `DataSeries` are provided, all series are filled so every array contains the same set of keys. Filled entries use `value: null`.

**Input**

```jsx
[
  { name: 'Canada', data: [{ key: 'Dogs', value: 23.43 }, { key: 'Cats', value: 6.64 }] },
  { name: 'United States', data: [{ key: 'Lizards', value: 350.13 }, { key: 'Turtles', value: 223.43 }] },
  { name: 'China', data: [{ key: 'Snakes', value: 0 }, { key: 'Eagles', value: 0 }] },
]
```

**Output**

```jsx
[
  {
    name: 'Canada',
    data: [
      { key: 'Dogs', value: 23.43 },
      { key: 'Cats', value: 6.64 },
      { key: 'Lizards', value: null },
      { key: 'Turtles', value: null },
      { key: 'Snakes', value: null },
      { key: 'Eagles', value: null },
    ],
  },
  {
    name: 'United States',
    data: [
      { key: 'Dogs', value: null },
      { key: 'Cats', value: null },
      { key: 'Lizards', value: 350.13 },
      { key: 'Turtles', value: 223.43 },
      { key: 'Snakes', value: null },
      { key: 'Eagles', value: null },
    ],
  },
  {
    name: 'China',
    data: [
      { key: 'Dogs', value: null },
      { key: 'Cats', value: null },
      { key: 'Lizards', value: null },
      { key: 'Turtles', value: null },
      { key: 'Snakes', value: 0 },
      { key: 'Eagles', value: 0 },
    ],
  },
]
```

### Linear data

Applies to `<LineChart />`, `<LineChartRelational />`, and `<StackedAreaChart />` — these assume matching keys across each `DataSeries`.

- Chart labels are built from the keys of the **longest** `DataSeries`; keys from shorter series are ignored.
- If different keys are provided, the `DataSeries` are combined into a longer set of data.
- **Exception:** a `DataSeries` with `isComparison: true` is *not* filled — comparison data can have different dates per key and different lengths.

```jsx
[
  {
    name: 'This Year',
    data: [
      { key: 'January', value: 10 },
      { key: 'February', value: 20 },
      { key: 'March', value: 30 },
      { key: 'April', value: 10 },
      { key: 'May', value: 20 },
      { key: 'June', value: 30 },
    ],
  },
  {
    name: 'Last Year',
    data: [
      { key: 'January', value: 0 },
      { key: 'February', value: 5 },
      { key: 'March', value: 10 },
      { key: 'April', value: 0 },
      { key: 'May', value: 5 },
      { key: 'June', value: 10 },
      { key: 'July', value: 10 },
      { key: 'August', value: 10 },
      { key: 'September', value: 10 },
      { key: 'October', value: 10 },
      { key: 'November', value: 10 },
      { key: 'December', value: 10 },
    ],
    isComparison: true,
  },
]
```

---

## 🏷 Labels

A label is a container plus a text element. The text can be a single line or up to 3 lines.

**Basic truncation**

- If a string is not wider than its container, it displays fully.
- If wider, it breaks and truncates up to 3 lines; after the 3rd line, end-line truncation shows `…`.
- If a single word is wider than the container, end-word truncation shows `…` at the end of that word, letting other words display fully.

**Diagonal labels**

- If a container becomes smaller than `45px`, labels display diagonally, up to a max width of `100px`.
- Diagonal labels only show a single line, with end-line truncation.

**Vertical labels**

- If a container becomes smaller than `14px`, labels display vertically, up to a max width of `80px`.
- Vertical labels only show a single line, with end-line truncation.

**Skipping labels (large data sets)**

For charts with data sets large enough that labels would render too small, labels are skipped until they can render horizontally. If they still can't render horizontally, labels are skipped and rendered diagonally or vertically, depending on container width.

---

## 🪝 Hooks

React hooks importable from `polaris-viz` or `polaris-viz-native`.

### `useYScale()`

Returns `yScale()` and formatted `ticks` based on the current chart size. Accounts for chart size and rounds the tick count accordingly. Recommended over writing a custom `yScale` function.

```tsx
const { yScale, ticks } = useYScale({
  drawableHeight: 300,
  formatYAxisLabel: (value) => `${value}`,
  integersOnly: false,
  max: 100,
  min: 0,
});

// ticks = [
//   { value: 0, formattedValue: "0", yOffset: 300 },
//   { value: 50, formattedValue: "50", yOffset: 150 },
//   { value: 100, formattedValue: "100", yOffset: 0 }
// ]
```

`minLabelSpace` determines how much space (in px) a label/tick takes up. Smaller number = more labels.

### `useUniqueId()`

Uses a given slug to create a unique ID string.

```ts
const donutId = useUniqueId('Donut');
// => `Donut-103`
```

### `useBrowserCheck()`

Checks `userAgent` and returns `true` for the current browser.

```ts
const { isChromium, isSafari, isFirefox } = useBrowserCheck();
```

---

## BarChart

Used to show comparison of different types, across categories or time. Bars can be stacked or side by side. Inherits height/width from its container; if no parent height can be calculated, falls back to `ChartContainer.minHeight` from the theme.

### Props

| Name | Description |
|---|---|
| `annotations` | An array of annotations to show on the chart. |
| `data` | A collection of named data sets to be rendered. An optional `color` can be provided per series, overriding the theme's `seriesColors` (defined in `PolarisVizProvider`). |
| `direction` | Changes the direction of the chart. |
| `emptyStateText` | Indicates to screen readers that a chart with no series data was rendered (empty array passed as `data`). Strongly recommended whenever `series` could be empty. |
| `isAnimated` | Whether to animate on initial render and on data updates. Animations are suppressed for users with reduced-motion preferences even if `true`. |
| `maxSeries` | Max number of series to show. Series beyond this number are bucketed into an "Other" series. |
| `onError` | Error callback. |
| `renderBucketLegendLabel` | Function called to render the bucket legend label shown when series are bucketed. Defaults to "Other". |
| `renderLegendContent` | Function called to render legend content instead of the default legend. No effect if `showLegend` is `false`. |
| `showLegend` | Renders a `<Legend />` underneath the chart. |
| `skipLinkText` | If provided, renders a `<SkipLink/>` button with this string — lets keyboard users skip all tabbable data points. Use for charts with large data sets. |
| `state` | Controls whether the chart displays Loading, Error, or Success state. |
| `theme` | The theme the chart inherits its styles from. |
| `type` | Changes bar grouping. If `stacked`, bar groups stack vertically; otherwise, individual bars render per data point per group. |
| `xAxisOptions` | Object defining the x-axis and its options. |
| `yAxisOptions` | Object defining the y-axis and its options. |

### BarChart variants to support

Reference list of BarChart Storybook story/variant types (from design reference screenshot) — use as the checklist of configurations the finance tracker's chart components should be able to render. Descriptions below are inferred from the variant name where not otherwise documented; verify exact behavior against the Polaris Viz source/Storybook before implementing.

- **Dynamic Data** — chart updates/re-renders as underlying data changes.
- **Hide X Axis** — renders without the x-axis.
- **Horizontal** — bars render horizontally instead of vertically (`direction` prop).
- **Horizontal Stacked** — horizontal bars with `type: stacked`.
- **Horizontal Stacked Without X Axis Labels** — horizontal stacked bars with x-axis labels hidden.
- **Integers Only** — y-axis ticks restricted to whole numbers (`integersOnly` on `useYScale`/`yAxisOptions`).
- **Interactive Custom Legend** — uses `renderLegendContent` to supply a custom, interactive legend instead of the default.
- **Max Series** — demonstrates the `maxSeries` prop bucketing extra series into "Other".
- **Negative Only** — all data values are negative (bars render below the baseline).
- **No Overflow Style** — bar/label rendering constrained so nothing overflows its container.
- **Overwritten Series Colors** — uses `DataSeries.color` to override theme `seriesColors`.
- **Series Colors Up To Sixteen** — demonstrates the theme's palette across up to 16 distinct series.
- **Single Bar** — a single-series/single-bar rendering.
- **Stacked** — vertical bars with `type: stacked`.
- **Without Rounded Corners** — bars rendered with square (non-rounded) corners.
- **Y Axis Percentages** — y-axis values formatted/rendered as percentages (`yAxisOptions.labelFormatter`).

---

## 📊 Chart Card Component Library (Design Reference)

The screenshots below are from a Figma "Components" page showing a repeating **chart card** pattern applied across a wide range of chart types, each rendered in two themes. Described in words below so the pattern can be rebuilt without the source file.

### Card anatomy

Every chart card follows the same wrapper structure, top and bottom:

1. **Header — "Meta Info" block**
   - Eyebrow label: `Meta Info`
   - Bold body title: `This is the body title`
   - Large bold primary value: e.g. `1,000 Value`
   - Muted subtitle: `This is a subtitle`
   - A refresh/sync icon pinned to the top-right corner of the card
2. **Tab row** — 4 pill-shaped `Tab` buttons directly under the header (filter/segment controls)
3. **Legend row** — colored dot markers + `Item` labels, one per series (count varies 1–5 depending on the chart), sitting directly above the chart
4. **Chart area** — fills the body of the card
5. **Tab row (repeated)** — a second row of 4 `Tab` pills below the chart, mirroring the top row
6. **Footer — "Meta Info" block (repeated)** — same structure as the header block, placed below the bottom tab row

So each card is bookended by matching Meta Info + Tab rows, with the legend and chart sandwiched in between.

### Theme variants

Every chart type is shown in two color modes, with the same series color palette carried across both:

- **Light** — white card background, near-black text, light-gray tab pills.
- **Dark** — near-navy card background, white text, slightly lighter navy tab pills.

### Chart type catalog

The library demonstrates the card pattern with the following chart types:

- **Scatter / bubble chart with trend line** — variable-sized bubble markers in a categorical palette (blue, green, orange, red) scattered across an X/Y grid, with a single smoothed trend line overlaid to show overall trajectory.
- **Line chart (multi-series)** — 3–5 overlapping, non-stacked line series in distinct colors over a shared x-axis.
- **Stacked area chart** — the same kind of multi-series data rendered as filled, layered area regions with gradient/blended fills, giving a layered "mountain range" look.
- **Radial / concentric ring chart** — several thin colored rings nested concentrically, one per category, with a center label.
- **Pie chart** — full circle split into 3–5 wedges, each annotated with a percentage.
- **Donut chart** — same as the pie chart but with a hollow center.
- **Radar / spider chart** — multi-axis polygon chart with several overlapping filled polygons (one per series/comparison group), category labels radiating around the perimeter.
- **Heatmap / matrix chart** — a grid of color-intensity cells (green→yellow→orange→red gradient) across two categorical axes (rows and columns both labeled), with a small horizontal gradient scale legend above the grid. Resembles a calendar heatmap or correlation matrix.
- **Diverging bar / order-book depth chart** — two mirrored horizontal bar sets (labeled `Shares` and `Bid/Ask`) extending outward from a central axis, one side green (bid), one side red (ask) — resembles a market depth chart / population pyramid.
- **Waveform chart** — a dense vertical bar/line pattern in cyan/teal rendered symmetrically above and below a center line, in the style of an audio waveform.
- **Checkerboard pattern card** — a plain black-and-white checkered grid; reads as a placeholder texture or an empty/no-data state rather than a real data visualization.
- **Horizontal stacked bar chart** — one horizontal bar per row/category, each bar split into 2–3 colored segments (e.g. purple/yellow/red) stacked end-to-end.
- **Histogram / bar chart (single series)** — a single-color vertical bar chart tracing a smooth bimodal (two-hump) distribution.
- **Histogram / bar chart (stacked, 3-series)** — the same bimodal shape rendered as a 3-color stacked bar chart.

### Icon library

A large icon set (100+ glyphs) is shown in matching light (white background) and dark (navy background) renderings side by side, for use across chart card headers, tabs, and controls. At a category level it covers:

- General UI actions — refresh, undo/redo, share, search, close (×), plus/minus, edit/pencil, expand/collapse corners, drag handle.
- Navigation — chevrons, directional arrows.
- Commerce — cart, price tag, dollar sign, gift.
- Communication — message bubble, envelope, notification bell, phone.
- Media — play, camera, video, headphones, film.
- Data/chart glyphs — bar chart, pie chart, line chart icons (for chart-type pickers/switchers).
- Status & security — lock, key, shield, eye / eye-off (visibility toggle).
- Connectivity — wifi, bluetooth, cloud, signal waves.
- Misc utility — calendar, folder, clock, map pin, house, flag, heart, power.

Note: the exact icon-by-icon inventory isn't fully legible at screenshot resolution — treat the above as a category map for scoping an icon set, and pull the authoritative list from the source Figma file/icon library before implementation rather than assuming any specific glyph is included.

---

## 🔤 Typography

A single type scale, shown largest/boldest to smallest/lightest:

| Style | Weight / Size | Color | Usage |
|---|---|---|---|
| **Value / Display** | Largest, bold | Dark/near-black | Big metric numbers, e.g. `1,092,648`. Same role as the `1,000 Value` field in the chart card header. |
| **Primary Text** | Large, bold | Dark/near-black | Heading-level text. Same role as `This is the body title`. |
| **Body (Paragraph — Regular)** | Medium-large, Regular weight, generous line-height | Dark/near-black | Paragraph copy (multi-line body content). Named text style: `Paragraph Regular`. |
| **Secondary Text** | Medium, regular weight | Muted gray | Supporting text directly under a heading. Same role as `This is a subtitle`. |
| **Caption Text** | Smallest, regular weight | Muted gray | Eyebrow label. Appears both above and below a content block (bookend pattern) — same role as the `Meta Info` label in the chart card anatomy above. |

This scale maps directly onto the chart card anatomy documented earlier: `Meta Info` = Caption Text, `This is the body title` = Primary Text, `1,000 Value` = Value/Display, `This is a subtitle` = Secondary Text.

---

## 🎨 Color Palette

### Categorical / series colors (6)
Vibrant, high-contrast hues used to differentiate chart series and legend items — matches the legend dot colors seen throughout the chart card library.

| Swatch | Hex | Description |
|---|---|---|
| 🟦 | `#05C7F2` | Sky blue / cyan |
| 🟩 | `#0FCA7A` | Green (emerald) |
| 🟧 | `#F7A23B` | Orange |
| 🟥 | `#F75D5F` | Red / coral |
| 🟨 | `#FBC62F` | Yellow / amber |
| 🟪 | `#695CFB` | Purple / indigo (blue-violet) |

### Blue-gray scale (10 steps)
Sequential tint-to-shade ramp, lightest to darkest. This is the primary/brand scale — its darkest steps correspond to the navy background used in the "dark theme" chart cards documented above.

| Step | Hex |
|---|---|
| 1 (lightest) | `#F0F4F8` |
| 2 | `#D9E2EC` |
| 3 | `#BCCCDC` |
| 4 | `#9FB3C8` |
| 5 | `#829AB1` |
| 6 | `#627D98` |
| 7 | `#486581` |
| 8 | `#334E68` |
| 9 | `#243B53` |
| 10 (darkest) | `#102A43` |

### Neutral gray scale (9 steps)
Sequential ramp from near-white through mid-gray to near-black, slightly warmer/more neutral than the blue-gray scale. Used for text, borders, and neutral backgrounds/surfaces.

| Step | Hex |
|---|---|
| 1 (lightest) | `#F7F8F9` |
| 2 | `#E7EAEE` |
| 3 | `#D0D5DD` |
| 4 | `#B8C0CC` |
| 5 | `#64748B` |
| 6 | `#4B5768` |
| 7 | `#323A46` |
| 8 | `#191D23` |
| 9 (darkest) | `#0D0F11` |

### Base / utility colors (4)
Foundational defaults for text, backgrounds, and borders, used outside the tinted scales above.

| Swatch | Hex | Description |
|---|---|---|
| ⬜ | `#FFFFFF` | White — used with shadow/elevation effects (e.g. card drop shadows on light backgrounds) |
| ⬛ | `#000000` | Black |
| ⬛ | `#2D2D2D` | Dark gray / charcoal (near-black, softer than pure black) |
| ◻️ | `#72777B` | Mid gray |
