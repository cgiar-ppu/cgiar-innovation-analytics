import { useState, useMemo } from 'react'
import {
  ResponsiveContainer,
  BarChart, Bar, LabelList,
  LineChart, Line,
  AreaChart, Area,
  PieChart, Pie, Cell,
  ScatterChart, Scatter,
  CartesianGrid, XAxis, YAxis, Tooltip, Legend,
} from 'recharts'
import { BarChart3, LineChart as LineChartIcon, PieChart as PieChartIcon, ChevronDown, ChevronUp } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import type { ChartData } from './chartDetector'

/** CGIAR brand palette -- optimized for chart readability and accessibility. */
const CHART_COLORS = [
  '#427730',   // CGIAR Forest Green (primary)
  '#0065BD',   // CGIAR Blue
  '#E37222',   // CGIAR Orange
  '#7AB800',   // CGIAR Lime Green
  '#8B1A4A',   // CGIAR Burgundy
  '#00A5DB',   // CGIAR Sky Blue
  '#F4B223',   // CGIAR Gold
  '#5C3D8F',   // CGIAR Purple
  '#009E73',   // CGIAR Teal
  '#D32F2F',   // CGIAR Red
]

const TOOLTIP_STYLE = {
  backgroundColor: 'var(--surface-2)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  color: 'var(--text)',
  fontSize: '12px',
  backdropFilter: 'blur(12px)',
}

const AXIS_TICK = { fill: 'var(--text-muted)', fontSize: 11 }

function getColor(index: number, explicit?: string): string {
  return explicit || CHART_COLORS[index % CHART_COLORS.length]!
}

function chartIcon(chartType: ChartData['chartType']) {
  switch (chartType) {
    case 'pie': return PieChartIcon
    case 'line': return LineChartIcon
    default: return BarChart3
  }
}

/** Width reserved for category labels on horizontal charts. */
const CATEGORY_AXIS_WIDTH = 208

/**
 * Category-axis tick that keeps entity labels readable: short labels render in
 * full; long ones lose the tail of the NAME but never the code prefix, and the
 * full text stays available as a native tooltip.
 */
function CategoryTick(props: Record<string, unknown>) {
  const { x, y, payload } = props as { x: number; y: number; payload: { value: string } }
  const full = String(payload?.value ?? '')
  const shown = full.length > 34 ? `${full.slice(0, 33)}…` : full
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={-6} y={0} dy={4} textAnchor="end" fill="var(--text-muted)" fontSize={11}>
        {shown}
        <title>{full}</title>
      </text>
    </g>
  )
}

function CartesianBase({ children, xAxisKey }: {
  children: React.ReactNode
  xAxisKey?: string
}) {
  return (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
      <XAxis
        dataKey={xAxisKey}
        tick={AXIS_TICK}
        axisLine={{ stroke: 'var(--border)' }}
        tickLine={false}
      />
      <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} />
      <Tooltip contentStyle={TOOLTIP_STYLE} />
      <Legend />
      {children}
    </>
  )
}

function RenderBar({ data, series, xAxisKey }: ChartData) {
  return (
    <BarChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
      <CartesianBase xAxisKey={xAxisKey}>
        {series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label || s.key}
            fill={getColor(i, s.color)}
            radius={[4, 4, 0, 0]}
            animationDuration={800}
          />
        ))}
      </CartesianBase>
    </BarChart>
  )
}

/**
 * Horizontal bar chart with the value printed on every bar.
 *
 * Used by the dashboard's "Top 10 Science Programs / Initiatives" chart
 * (feedback item F14: the top entity must be readable OUTRIGHT — full name on
 * the axis, value visible without hovering).
 */
function RenderHorizontalBar({ data, series, xAxisKey }: ChartData) {
  const key = series[0]?.key
  if (!key) return null

  return (
    <BarChart
      data={data}
      layout="vertical"
      margin={{ top: 4, right: 44, bottom: 4, left: 0 }}
    >
      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
      <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
      <YAxis
        type="category"
        dataKey={xAxisKey}
        width={CATEGORY_AXIS_WIDTH}
        interval={0}
        tick={<CategoryTick />}
        axisLine={{ stroke: 'var(--border)' }}
        tickLine={false}
      />
      <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--surface-2)', fillOpacity: 0.4 }} />
      {series.map((s, i) => (
        <Bar
          key={s.key}
          dataKey={s.key}
          name={s.label || s.key}
          fill={getColor(i, s.color)}
          radius={[0, 4, 4, 0]}
          animationDuration={800}
        >
          {/* F14: the number is always on screen, never hover-only. */}
          <LabelList
            dataKey={s.key}
            position="right"
            style={{ fill: 'var(--text)', fontSize: 11, fontWeight: 600 }}
          />
        </Bar>
      ))}
    </BarChart>
  )
}

/**
 * Horizontal STACKED bar chart with a legend.
 *
 * Used by the dashboard's "Top 10 Countries by Innovation Readiness" chart
 * (feedback item F13): one bar per country, segmented by IRL level. Horizontal
 * because country names are long ("The Socialist Republic of Viet Nam") and
 * would be unreadable rotated under a vertical bar.
 *
 * Series order is meaningful — the backend emits readiness levels low-to-high
 * with "Not reported" last — so segments stack in readiness order.
 */
function RenderStackedBar({ data, series, xAxisKey }: ChartData) {
  return (
    <BarChart
      data={data}
      layout="vertical"
      margin={{ top: 4, right: 16, bottom: 4, left: 0 }}
    >
      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
      <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
      <YAxis
        type="category"
        dataKey={xAxisKey}
        width={CATEGORY_AXIS_WIDTH}
        interval={0}
        tick={<CategoryTick />}
        axisLine={{ stroke: 'var(--border)' }}
        tickLine={false}
      />
      <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--surface-2)', fillOpacity: 0.4 }} />
      <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} iconSize={8} />
      {series.map((s, i) => (
        <Bar
          key={s.key}
          dataKey={s.key}
          name={s.label || s.key}
          stackId="irl"
          fill={getColor(i, s.color)}
          animationDuration={800}
        />
      ))}
    </BarChart>
  )
}

function RenderLine({ data, series, xAxisKey }: ChartData) {
  return (
    <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
      <CartesianBase xAxisKey={xAxisKey}>
        {series.map((s, i) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label || s.key}
            stroke={getColor(i, s.color)}
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
            animationDuration={800}
          />
        ))}
      </CartesianBase>
    </LineChart>
  )
}

function RenderArea({ data, series, xAxisKey }: ChartData) {
  const gradientId = useMemo(() => `area-grad-${Math.random().toString(36).slice(2, 8)}`, [])

  return (
    <AreaChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
      <defs>
        {series.map((s, i) => (
          <linearGradient key={s.key} id={`${gradientId}-${i}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={getColor(i, s.color)} stopOpacity={0.3} />
            <stop offset="95%" stopColor={getColor(i, s.color)} stopOpacity={0} />
          </linearGradient>
        ))}
      </defs>
      <CartesianBase xAxisKey={xAxisKey}>
        {series.map((s, i) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label || s.key}
            stroke={getColor(i, s.color)}
            strokeWidth={2}
            fillOpacity={1}
            fill={`url(#${gradientId}-${i})`}
            animationDuration={800}
          />
        ))}
      </CartesianBase>
    </AreaChart>
  )
}

function RenderStackedArea({ data, series, xAxisKey }: ChartData) {
  const gradientId = useMemo(() => `sa-grad-${Math.random().toString(36).slice(2, 8)}`, [])

  return (
    <AreaChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
      <defs>
        {series.map((s, i) => (
          <linearGradient key={s.key} id={`${gradientId}-${i}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={getColor(i, s.color)} stopOpacity={0.4} />
            <stop offset="95%" stopColor={getColor(i, s.color)} stopOpacity={0.05} />
          </linearGradient>
        ))}
      </defs>
      <CartesianBase xAxisKey={xAxisKey}>
        {series.map((s, i) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label || s.key}
            stackId="1"
            stroke={getColor(i, s.color)}
            strokeWidth={2}
            fillOpacity={1}
            fill={`url(#${gradientId}-${i})`}
            animationDuration={800}
          />
        ))}
      </CartesianBase>
    </AreaChart>
  )
}

function RenderPie({ data, series }: ChartData) {
  const key = series[0]?.key
  if (!key) return null

  const total = data.reduce((sum, d) => sum + (Number(d[key]) || 0), 0)

  return (
    <PieChart>
      <Tooltip contentStyle={TOOLTIP_STYLE} />
      <Legend />
      <Pie
        data={data}
        dataKey={key}
        nameKey={Object.keys(data[0] || {}).find(k => k !== key) || 'name'}
        cx="50%"
        cy="50%"
        innerRadius="40%"
        outerRadius="75%"
        paddingAngle={2}
        animationDuration={800}
        label={({ percent }: { percent?: number }) => `${((percent ?? 0) * 100).toFixed(0)}%`}
      >
        {data.map((_, i) => (
          <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
        ))}
      </Pie>
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="var(--text)"
        fontSize={14}
        fontWeight={600}
      >
        {total.toLocaleString()}
      </text>
    </PieChart>
  )
}

function RenderScatter({ data, series, xAxisKey }: ChartData) {
  const xKey = xAxisKey || series[0]?.key
  const yKey = series.length > 1 ? series[1]!.key : series[0]?.key
  return (
    <ScatterChart margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
      <XAxis dataKey={xKey} tick={AXIS_TICK} axisLine={{ stroke: 'var(--border)' }} tickLine={false} name={xKey} type="number" />
      <YAxis dataKey={yKey} tick={AXIS_TICK} axisLine={false} tickLine={false} name={yKey} type="number" />
      <Tooltip contentStyle={TOOLTIP_STYLE} />
      <Legend />
      <Scatter name={series[0]?.label || 'Data'} data={data} fill={getColor(0, series[0]?.color)} animationDuration={800} />
    </ScatterChart>
  )
}

/** Per-type body height. Horizontal/stacked charts need more vertical room. */
const CHART_HEIGHTS: Partial<Record<ChartData['chartType'], number>> = {
  horizontalBar: 360,
  stackedBar: 360,
}

interface InteractiveChartProps {
  data: ChartData
  className?: string
}

export function InteractiveChart({ data, className = '' }: InteractiveChartProps) {
  const [collapsed, setCollapsed] = useState(false)
  const Icon = chartIcon(data.chartType)

  const renderChart = () => {
    switch (data.chartType) {
      case 'bar': return <RenderBar {...data} />
      case 'multiBar': return <RenderBar {...data} />
      case 'horizontalBar': return <RenderHorizontalBar {...data} />
      case 'stackedBar': return <RenderStackedBar {...data} />
      case 'line': return <RenderLine {...data} />
      case 'area': return <RenderArea {...data} />
      case 'stackedArea': return <RenderStackedArea {...data} />
      case 'pie': return <RenderPie {...data} />
      case 'scatter': return <RenderScatter {...data} />
      default: return null
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`bg-[var(--surface-solid)] rounded-xl border border-[var(--border)] shadow-sm transition-shadow hover:shadow-md overflow-hidden ${className}`}
    >
      {/* Title bar */}
      <button
        onClick={() => setCollapsed(prev => !prev)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-white/[0.02] transition-colors"
      >
        <Icon size={14} className="text-[var(--text-muted)] flex-shrink-0" />
        <span className="text-sm font-medium text-[var(--text-muted)] font-serif flex-1 truncate">
          {data.title || `${data.chartType.charAt(0).toUpperCase() + data.chartType.slice(1)} Chart`}
        </span>
        {collapsed ? <ChevronDown size={14} className="text-[var(--text-muted)]" /> : <ChevronUp size={14} className="text-[var(--text-muted)]" />}
      </button>

      {/* Chart body */}
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            {data.description && (
              <p className="px-4 pb-1 text-xs text-[var(--text-muted)]">{data.description}</p>
            )}
            <div className="px-4 pb-4" style={{ height: CHART_HEIGHTS[data.chartType] ?? 300 }}>
              <ResponsiveContainer width="100%" height="100%">
                {renderChart()!}
              </ResponsiveContainer>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
