import { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Box,
  Typography,
  MenuItem,
  InputAdornment,
  Alert,
  Divider,
  ToggleButtonGroup,
  ToggleButton,
  CircularProgress,
} from '@mui/material';
import { fetchFundNavAtDate } from '../../api';

export interface TransactionFormData {
  asset_type: string;
  asset_code: string;
  asset_name?: string;
  transaction_type: string;
  shares: number;
  price: number;
  total_amount?: number;
  fees?: number;
  transaction_date: string;
  notes?: string;
}

interface TransactionFormProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: TransactionFormData) => Promise<void>;
  assetCode?: string;
  assetName?: string;
  assetType?: string;
}

const TRANSACTION_TYPES = [
  { value: 'buy', labelKey: 'portfolio.tx_buy' },
  { value: 'sell', labelKey: 'portfolio.tx_sell' },
  { value: 'dividend', labelKey: 'portfolio.tx_dividend' },
  { value: 'split', labelKey: 'portfolio.tx_split' },
  { value: 'transfer_in', labelKey: 'portfolio.tx_transfer_in' },
  { value: 'transfer_out', labelKey: 'portfolio.tx_transfer_out' },
];

export default function TransactionForm({
  open,
  onClose,
  onSubmit,
  assetCode = '',
  assetName = '',
  assetType = 'stock',
}: TransactionFormProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [entryMode, setEntryMode] = useState<'shares' | 'amount'>(assetType === 'fund' ? 'amount' : 'shares');
  const [amountInput, setAmountInput] = useState<number>(0);
  const [navLoading, setNavLoading] = useState(false);
  const [navHint, setNavHint] = useState('');
  const [formData, setFormData] = useState<TransactionFormData>({
    asset_type: assetType,
    asset_code: assetCode,
    asset_name: assetName,
    transaction_type: 'buy',
    shares: 0,
    price: 0,
    fees: 0,
    transaction_date: new Date().toISOString().slice(0, 10),
    notes: '',
  });

  const supportsAmountMode = useMemo(() => (
    formData.asset_type === 'fund' && ['buy', 'transfer_in'].includes(formData.transaction_type)
  ), [formData.asset_type, formData.transaction_type]);

  // Reset form when dialog opens or asset props change
  useEffect(() => {
    if (open) {
      setFormData({
        asset_type: assetType,
        asset_code: assetCode,
        asset_name: assetName,
        transaction_type: 'buy',
        shares: 0,
        price: 0,
        fees: 0,
        transaction_date: new Date().toISOString().slice(0, 10),
        notes: '',
      });
      setEntryMode(assetType === 'fund' ? 'amount' : 'shares');
      setAmountInput(0);
      setNavHint('');
      setError('');
    }
  }, [open, assetCode, assetName, assetType]);

  const handleChange = (field: keyof TransactionFormData, value: any) => {
    setFormData((prev) => ({
      ...prev,
      [field]: ['shares', 'price', 'fees'].includes(field as string) ? parseFloat(value) || 0 : value,
    }));
  };

  useEffect(() => {
    if (!supportsAmountMode && entryMode === 'amount') {
      setEntryMode('shares');
    }
  }, [supportsAmountMode, entryMode]);

  useEffect(() => {
    if (!open || !supportsAmountMode || entryMode !== 'amount') {
      setNavLoading(false);
      if (!supportsAmountMode) {
        setNavHint('');
      }
      return;
    }

    if (!formData.asset_code || !formData.transaction_date) {
      setNavHint('');
      return;
    }

    let cancelled = false;
    setNavLoading(true);
    setNavHint('');

    fetchFundNavAtDate(formData.asset_code.trim(), formData.transaction_date)
      .then((res) => {
        if (cancelled) return;
        setFormData((prev) => ({ ...prev, price: res.unit_nav }));
        setNavHint(
          res.is_exact
            ? `已自动填充净值 ${res.unit_nav.toFixed(4)}（${res.nav_date}）`
            : `该日无净值，已填最近净值 ${res.unit_nav.toFixed(4)}（${res.nav_date}）`
        );
      })
      .catch(() => {
        if (cancelled) return;
        setNavHint('未能自动获取净值，请手动输入成交价格');
      })
      .finally(() => {
        if (!cancelled) {
          setNavLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    open,
    supportsAmountMode,
    entryMode,
    formData.asset_code,
    formData.transaction_date,
  ]);

  const computedShares = useMemo(() => {
    if (entryMode !== 'amount') return formData.shares;
    if (formData.price <= 0) return 0;
    const netAmount = amountInput - (formData.fees || 0);
    if (netAmount <= 0) return 0;
    return netAmount / formData.price;
  }, [entryMode, amountInput, formData.fees, formData.price, formData.shares]);

  const totalAmount = entryMode === 'amount' ? amountInput : formData.shares * formData.price;

  const handleSubmit = async () => {
    const sharesToSubmit = entryMode === 'amount' ? computedShares : formData.shares;

    if (entryMode === 'amount') {
      if (amountInput <= 0) {
        setError('请输入有效的总金额');
        return;
      }
      if ((formData.fees || 0) < 0) {
        setError('手续费不能为负数');
        return;
      }
      if (amountInput <= (formData.fees || 0)) {
        setError('总金额必须大于手续费');
        return;
      }
    }

    if (sharesToSubmit <= 0) {
      setError(t('portfolio.error_shares'));
      return;
    }
    if (formData.price <= 0) {
      setError(t('portfolio.error_price'));
      return;
    }
    if (!formData.transaction_date) {
      setError(t('portfolio.error_date'));
      return;
    }
    if (!formData.asset_code) {
      setError(t('portfolio.error_asset_code'));
      return;
    }

    setLoading(true);
    setError('');
    try {
      await onSubmit({
        ...formData,
        shares: sharesToSubmit,
        total_amount: totalAmount,
      });
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || t('portfolio.error_save'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      PaperProps={{ sx: { borderRadius: '16px' } }}
    >
      <DialogTitle sx={{ fontWeight: 700, borderBottom: '1px solid', borderColor: 'divider' }}>
        {t('portfolio.add_transaction')}
      </DialogTitle>
      <DialogContent sx={{ pt: 3 }}>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <Box sx={{ display: 'flex', gap: 2, mb: 2, mt: 1 }}>
          <TextField
            select
            label={t('portfolio.asset_type')}
            value={formData.asset_type}
            onChange={(e) => handleChange('asset_type', e.target.value)}
            size="small"
            sx={{ width: 120 }}
          >
            <MenuItem value="stock">{t('portfolio.stock_type')}</MenuItem>
            <MenuItem value="fund">{t('portfolio.fund_type')}</MenuItem>
          </TextField>
          <TextField
            label={t('portfolio.asset_code')}
            value={formData.asset_code}
            onChange={(e) => handleChange('asset_code', e.target.value)}
            size="small"
            sx={{ flex: 1 }}
          />
          <TextField
            label={t('portfolio.asset_name')}
            value={formData.asset_name}
            onChange={(e) => handleChange('asset_name', e.target.value)}
            size="small"
            sx={{ flex: 1 }}
          />
        </Box>

        <Divider sx={{ my: 2 }} />

        <TextField
          select
          fullWidth
          label={t('portfolio.transaction_type')}
          value={formData.transaction_type}
          onChange={(e) => handleChange('transaction_type', e.target.value)}
          size="small"
          sx={{ mb: 2 }}
        >
          {TRANSACTION_TYPES.map((type) => (
            <MenuItem key={type.value} value={type.value}>
              {t(type.labelKey)}
            </MenuItem>
          ))}
        </TextField>

        {supportsAmountMode && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 1 }}>
              录入方式
            </Typography>
            <ToggleButtonGroup
              value={entryMode}
              exclusive
              onChange={(_, value) => {
                if (value) setEntryMode(value);
              }}
              size="small"
              sx={{ width: '100%' }}
            >
              <ToggleButton value="amount" sx={{ flex: 1 }}>
                按金额
              </ToggleButton>
              <ToggleButton value="shares" sx={{ flex: 1 }}>
                按份额
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>
        )}

        {entryMode === 'amount' ? (
          <Box sx={{ mb: 2 }}>
            <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
              <TextField
                label={t('portfolio.total_amount')}
                type="number"
                value={amountInput || ''}
                onChange={(e) => setAmountInput(parseFloat(e.target.value) || 0)}
                size="small"
                fullWidth
                slotProps={{
                  input: {
                    startAdornment: <InputAdornment position="start">¥</InputAdornment>,
                  },
                }}
              />
              <TextField
                label={t('portfolio.price')}
                type="number"
                value={formData.price || ''}
                onChange={(e) => handleChange('price', e.target.value)}
                size="small"
                fullWidth
                slotProps={{
                  input: {
                    startAdornment: <InputAdornment position="start">¥</InputAdornment>,
                    endAdornment: navLoading ? <CircularProgress size={16} /> : undefined,
                  },
                }}
              />
            </Box>
            <TextField
              label={t('portfolio.shares')}
              type="number"
              value={computedShares > 0 ? computedShares.toFixed(4) : ''}
              size="small"
              fullWidth
              slotProps={{
                input: {
                  readOnly: true,
                  endAdornment: <InputAdornment position="end">{t('portfolio.shares_unit')}</InputAdornment>,
                },
              }}
              helperText={navHint || '份额 = (总金额 - 手续费) / 价格'}
            />
          </Box>
        ) : (
        <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
          <TextField
            label={t('portfolio.shares')}
            type="number"
            value={formData.shares || ''}
            onChange={(e) => handleChange('shares', e.target.value)}
            size="small"
            fullWidth
            slotProps={{
              input: {
                endAdornment: <InputAdornment position="end">{t('portfolio.shares_unit')}</InputAdornment>,
              },
            }}
          />
          <TextField
            label={t('portfolio.price')}
            type="number"
            value={formData.price || ''}
            onChange={(e) => handleChange('price', e.target.value)}
            size="small"
            fullWidth
            slotProps={{
              input: {
                startAdornment: <InputAdornment position="start">¥</InputAdornment>,
              },
            }}
          />
        </Box>
        )}

        <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
          <TextField
            label={t('portfolio.fees')}
            type="number"
            value={formData.fees || ''}
            onChange={(e) => handleChange('fees', e.target.value)}
            size="small"
            fullWidth
            slotProps={{
              input: {
                startAdornment: <InputAdornment position="start">¥</InputAdornment>,
              },
            }}
          />
          <TextField
            label={t('portfolio.transaction_date')}
            type="date"
            value={formData.transaction_date}
            onChange={(e) => handleChange('transaction_date', e.target.value)}
            size="small"
            fullWidth
            slotProps={{ inputLabel: { shrink: true } }}
          />
        </Box>

        <Box sx={{ mb: 2, p: 1.5, bgcolor: 'action.hover', borderRadius: '8px' }}>
          <Typography variant="body2" color="text.secondary">
            {t('portfolio.total_amount')}:
            <Typography component="span" sx={{ fontWeight: 700, ml: 1, fontFamily: 'JetBrains Mono, monospace' }}>
              ¥{totalAmount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
            </Typography>
          </Typography>
        </Box>

        <TextField
          label={t('portfolio.notes')}
          value={formData.notes}
          onChange={(e) => handleChange('notes', e.target.value)}
          multiline
          rows={2}
          fullWidth
          size="small"
        />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={loading}>
          {t('common.cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={loading}
          sx={{ bgcolor: '#6366f1', '&:hover': { bgcolor: '#4f46e5' } }}
        >
          {loading ? t('common.saving') : t('common.save')}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
