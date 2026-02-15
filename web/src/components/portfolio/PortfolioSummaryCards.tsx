import { Grid, Paper, Typography, Box, Skeleton } from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import PieChartIcon from '@mui/icons-material/PieChart';
import { useTranslation } from 'react-i18next';

interface PortfolioSummaryCardsProps {
  totalValue: number;
  totalCost: number;
  totalPnl: number;
  totalPnlPct: number;
  positionsCount: number;
  loading?: boolean;
}

export default function PortfolioSummaryCards({
  totalValue,
  totalCost,
  totalPnl,
  totalPnlPct,
  positionsCount,
  loading = false,
}: PortfolioSummaryCardsProps) {
  const { t } = useTranslation();

  const cards = [
    {
      label: t('portfolio.total_value'),
      value: `\u00a5${totalValue.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`,
      hint: '\u53e3\u5f84\uff1a\u5f53\u524d\u6301\u4ed3\u5e02\u503c\uff08\u4e0d\u542b\u73b0\u91d1\uff09',
      icon: <AccountBalanceIcon sx={{ color: '#6366f1' }} />,
      color: undefined,
    },
    {
      label: t('portfolio.total_cost'),
      value: `\u00a5${totalCost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`,
      hint: '\u53e3\u5f84\uff1a\u7d2f\u8ba1\u6295\u5165\u6210\u672c\uff08\u4e70\u5165+\u8d39\u7528\uff09',
      icon: <PieChartIcon sx={{ color: '#8b5cf6' }} />,
      color: undefined,
    },
    {
      label: t('portfolio.total_pnl'),
      value: `${totalPnl >= 0 ? '+' : ''}\u00a5${totalPnl.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`,
      hint: '\u8ba1\u7b97\uff1a\u603b\u5e02\u503c - \u603b\u6210\u672c',
      icon: totalPnl >= 0 ? <TrendingUpIcon color="success" /> : <TrendingDownIcon color="error" />,
      color: totalPnl >= 0 ? 'success.main' : 'error.main',
    },
    {
      label: t('portfolio.pnl_pct'),
      value: `${totalPnlPct >= 0 ? '+' : ''}${totalPnlPct.toFixed(2)}%`,
      hint: '\u8ba1\u7b97\uff1a\u603b\u6536\u76ca \u00f7 \u603b\u6210\u672c',
      icon: totalPnlPct >= 0 ? <TrendingUpIcon color="success" /> : <TrendingDownIcon color="error" />,
      color: totalPnlPct >= 0 ? 'success.main' : 'error.main',
    },
  ];

  return (
    <Grid container spacing={2}>
      {cards.map((card, index) => (
        <Grid key={index} size={{ xs: 6, sm: 6, md: 3 }}>
          <Paper
            sx={{
              p: 2,
              borderRadius: '12px',
              background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.02) 0%, rgba(139, 92, 246, 0.02) 100%)',
              border: '1px solid',
              borderColor: 'divider',
            }}
          >
            {loading ? (
              <>
                <Skeleton width="60%" height={20} />
                <Skeleton width="80%" height={36} sx={{ mt: 1 }} />
              </>
            ) : (
              <>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                  <Typography variant="caption" color="text.secondary">
                    {card.label}
                  </Typography>
                  {card.icon}
                </Box>
                <Typography
                  variant="h5"
                  sx={{
                    fontWeight: 700,
                    fontFamily: 'JetBrains Mono, monospace',
                    color: card.color,
                    fontSize: { xs: '1.1rem', sm: '1.5rem' },
                  }}
                >
                  {card.value}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {card.hint}
                </Typography>
              </>
            )}
          </Paper>
        </Grid>
      ))}
    </Grid>
  );
}
