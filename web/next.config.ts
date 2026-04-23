import type { NextConfig } from '@/next'
import { fileURLToPath } from 'node:url'
import createMDX from '@next/mdx'
import { codeInspectorPlugin } from 'code-inspector-plugin'
import { env } from './env'

const isDev = process.env.NODE_ENV === 'development'
const turbopackRoot = fileURLToPath(new URL('..', import.meta.url))
const withMDX = createMDX()

const nextConfig: NextConfig = {
  basePath: env.NEXT_PUBLIC_BASE_PATH,
  transpilePackages: ['@t3-oss/env-core', '@t3-oss/env-nextjs', 'echarts', 'zrender'],
  turbopack: {
    root: turbopackRoot,
    resolveAlias: {
      'lucide-react/dynamicIconImports': 'lucide-react/dynamicIconImports.mjs',
    },
    rules: codeInspectorPlugin({
      bundler: 'turbopack',
      needEnvInspector: true,
    }),
  },
  productionBrowserSourceMaps: false, // enable browser source map generation during the production build
  // Configure pageExtensions to include md and mdx
  pageExtensions: ['ts', 'tsx', 'js', 'jsx', 'md', 'mdx'],
  typescript: {
    // https://nextjs.org/docs/api-reference/next.config.js/ignoring-typescript-errors
    ignoreBuildErrors: true,
  },
  async redirects() {
    return [
      {
        source: '/',
        destination: '/apps',
        permanent: false,
      },
    ]
  },
  output: 'standalone',
  compiler: {
    removeConsole: isDev ? false : { exclude: ['warn', 'error'] },
  },
  webpack(config) {
    config.experiments = {
      ...config.experiments,
      asyncWebAssembly: true,
    }
    config.module.rules.push({
      test: /\.wasm$/,
      type: 'webassembly/async',
    })
    return config
  },
}

export default withMDX(nextConfig)
