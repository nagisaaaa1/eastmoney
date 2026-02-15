import React from 'react';
import {
  Box,
  Paper,
  Typography,
  Chip,
  CircularProgress,
  Tooltip,
  useTheme,
  alpha,
} from '@mui/material';
import {
  TrendingUp,
  TrendingDown,
  TrendingFlat,
  Shield,
  Speed,
  HealthAndSafety,
  ShowChart,
} from '@mui/icons-material';
import { useTranslation } from 'react-i18next';
import AnimatedNumber from './AnimatedNumber';
import SparklineChart from './SparklineChart';

interface PortfolioHeaderProps {
  totalValue: number;
  totalPnl: number;
  totalPnlPct: number;
  sparklineData?: {
    values: number[];
    dates: string[];
    trend: 'up' | 'down' | 'flat';
  };
  beta?: number | null;
  betaStatus?: string;
  sharpeRatio?: number | null;
  sharpeStatus?: string;
  healthScore?: number;
  healthGrade?: string;
  loading?: boolean;
}

const PortfolioHeader: React.FC<PortfolioHeaderProps> = ({
  totalValue,
  totalPnl,
  totalPnlPct,
  sparklineData,
  loading = false,
}) => {
  const theme = useTheme();
  const { t } = useTranslation();



  const TrendIcon = () => {
    if (!sparklineData) return <TrendingFlat />;
    switch (sparklineData.trend) {
      case 'up': return <TrendingUp sx={{ color: theme.palette.success.main }} />;
      case 'down': return <TrendingDown sx={{ color: theme.palette.error.main }} />;
      default: return <TrendingFlat sx={{ color: theme.palette.text.secondary }} />;
    }
  };

  return (
    <Paper
      elevation={0}
      sx={{
        p: 3,
        mb: 3,
        background: `linear-gradient(135deg, ${alpha(theme.palette.primary.main, 0.05)} 0%, ${alpha(theme.palette.background.paper, 0.95)} 100%)`,
        backdropFilter: 'blur(10px)',
        border: `1px solid ${alpha(theme.palette.divider, 0.1)}`,
        borderRadius: 3,
      }}
    >
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '2fr 1fr 1fr 1fr' },
          gap: 3,
          alignItems: 'center',
        }}
      >
        {/* Total Value + Sparkline */}
        <Box>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            {t('portfolio.totalAssets', '\u6301\u4ed3\u5e02\u503c\uff08\u4e0d\u542b\u73b0\u91d1\uff09')}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
            {t('portfolio.totalAssetsHint', '\u53e3\u5f84\uff1a\u5f53\u524d\u6301\u4ed3\u6309\u6700\u65b0\u4ef7\u683c\u4f30\u7b97\uff0c\u4e0d\u5305\u542b\u53ef\u7528\u73b0\u91d1')}
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Box>
              <AnimatedNumber
                value={totalValue}
                prefix="¥"
                decimals={2}
                size="large"
                color="primary"
              />
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                <TrendIcon />
                <AnimatedNumber
                  value={totalPnl}
                  prefix="¥"
                  decimals={2}
                  size="small"
                  color={totalPnl >= 0 ? 'success' : 'error'}
                  showSign
                />
                <Typography
                  variant="body2"
                  sx={{
                    color: totalPnlPct >= 0 ? 'success.main' : 'error.main',
                  }}
                >
                  ({totalPnlPct >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%)
                </Typography>
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
                {t('portfolio.pnlFormula', '\u6536\u76ca\u989d = \u6301\u4ed3\u5e02\u503c - \u6295\u5165\u6210\u672c\uff08\u7d2f\u8ba1\u4e70\u5165+\u8d39\u7528\uff09\uff1b\u6536\u76ca\u7387 = \u6536\u76ca\u989d \u00f7 \u6295\u5165\u6210\u672c')}
              </Typography>
            </Box>
            {sparklineData && sparklineData.values.length > 1 && (
              <Box sx={{ width: 100, height: 50 }}>
                <SparklineChart
                  data={sparklineData.values}
                  dates={sparklineData.dates}
                  height={50}
                />
              </Box>
            )}
          </Box>
        </Box>
      </Box>
    </Paper>
  );
};

export default PortfolioHeader;
