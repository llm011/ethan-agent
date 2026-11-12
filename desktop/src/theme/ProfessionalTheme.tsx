/**
 * 专业级 Material Design 3 主题系统
 * 
 * 设计理念：
 * - 消除"塑料感"：使用微妙的阴影和边框
 * - 克制优雅的色彩（参考 Linear、Notion）
 * - 一致性：与 Android/Web/Desktop 完全同步
 */

import { useMemo } from 'react';
import { ThemeProvider as MuiThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';

// 专业级调色板 - 克制、高级
const professionalLightColors = {
  primary: {
    main: '#1A73E8',        // 克制蓝
    light: '#4A90E2',
    dark: '#0056B3',
  },
  secondary: {
    main: '#5F6368',        // 中性灰
    light: '#8C9197',
    dark: '#4A4D51',
  },
  background: {
    default: '#F8F9FA',     // 浅灰背景
    paper: '#FFFFFF',       // 纯白卡片
  },
  surface: {
    main: '#FFFFFF',
    variant: '#E6E8EB',     // 微妙边界
  },
  text: {
    primary: '#1A1C1E',
    secondary: '#5F6368',
    disabled: '#9AA0A6',
  },
  border: {
    light: '#E6E8EB',
    medium: '#C5C8CC',
    dark: '#9AA0A6',
  },
  shadow: {
    xs: '0 1px 2px rgba(0,0,0,0.04)',
    sm: '0 2px 4px rgba(0,0,0,0.06)',
    md: '0 4px 8px rgba(0,0,0,0.08)',
    lg: '0 8px 16px rgba(0,0,0,0.1)',
  },
};

const professionalDarkColors = {
  primary: {
    main: '#8AB4F8',
    light: '#BBD6FB',
    dark: '#4A90E2',
  },
  secondary: {
    main: '#B0B3B8',
    light: '#D6D9DD',
    dark: '#8C8F94',
  },
  background: {
    default: '#121212',     // 深灰黑
    paper: '#1E1E1E',       // 深灰卡片
  },
  surface: {
    main: '#1E1E1E',
    variant: '#2C2E30',
  },
  text: {
    primary: '#E3E6EA',
    secondary: '#B0B3B8',
    disabled: '#8C8F94',
  },
  border: {
    light: '#2C2E30',
    medium: '#43474B',
    dark: '#5F6368',
  },
  shadow: {
    xs: '0 1px 2px rgba(0,0,0,0.3)',
    sm: '0 2px 4px rgba(0,0,0,0.4)',
    md: '0 4px 8px rgba(0,0,0,0.5)',
    lg: '0 8px 16px rgba(0,0,0,0.6)',
  },
};

// 专业排版系统
const typography = {
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  h1: { fontSize: '32px', fontWeight: 600, lineHeight: 1.25 },
  h2: { fontSize: '28px', fontWeight: 600, lineHeight: 1.28 },
  h3: { fontSize: '24px', fontWeight: 600, lineHeight: 1.33 },
  h4: { fontSize: '20px', fontWeight: 600, lineHeight: 1.4 },
  h5: { fontSize: '16px', fontWeight: 500, lineHeight: 1.5 },
  h6: { fontSize: '14px', fontWeight: 500, lineHeight: 1.43 },
  body1: { fontSize: '16px', fontWeight: 400, lineHeight: 1.5 },
  body2: { fontSize: '14px', fontWeight: 400, lineHeight: 1.43 },
  button: { fontSize: '14px', fontWeight: 500, letterSpacing: '0.15px' },
  caption: { fontSize: '12px', fontWeight: 400, letterSpacing: '0.4px' },
};

// 圆角系统
const shape = {
  borderRadius: 8,          // 按钮、输入框
  borderRadiusLG: 12,       // 卡片
  borderRadiusXL: 16,       // 对话框
};

// 阴影系统
const shadows = {
  1: professionalLightColors.shadow.xs,
  2: professionalLightColors.shadow.sm,
  3: professionalLightColors.shadow.md,
  4: professionalLightColors.shadow.lg,
};

export function ProfessionalThemeProvider({ children }: { children: React.ReactNode }) {
  const lightTheme = useMemo(() => createTheme({
    palette: {
      mode: 'light',
      primary: { main: professionalLightColors.primary.main },
      secondary: { main: professionalLightColors.secondary.main },
      background: {
        default: professionalLightColors.background.default,
        paper: professionalLightColors.background.paper,
      },
      text: professionalLightColors.text,
      divider: professionalLightColors.border.medium,
    },
    typography,
    shape,
    components: {
      MuiCard: {
        styleOverrides: {
          root: {
            boxShadow: shadows[1],
            borderRadius: shape.borderRadiusLG,
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: shape.borderRadius,
            textTransform: 'none' as const,
            fontWeight: 500,
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: shape.borderRadius,
            },
          },
        },
      },
    },
  }), []);

  const darkTheme = useMemo(() => createTheme({
    palette: {
      mode: 'dark',
      primary: { main: professionalDarkColors.primary.main },
      secondary: { main: professionalDarkColors.secondary.main },
      background: {
        default: professionalDarkColors.background.default,
        paper: professionalDarkColors.background.paper,
      },
      text: professionalDarkColors.text,
      divider: professionalDarkColors.border.medium,
    },
    typography,
    shape,
    components: {
      MuiCard: {
        styleOverrides: {
          root: {
            boxShadow: shadows[1],
            borderRadius: shape.borderRadiusLG,
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: shape.borderRadius,
            textTransform: 'none' as const,
            fontWeight: 500,
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: shape.borderRadius,
            },
          },
        },
      },
    },
  }), []);

  return (
    <MuiThemeProvider theme={lightTheme}>
      <CssBaseline />
      {children}
    </MuiThemeProvider>
  );
}

export { professionalLightColors, professionalDarkColors };
