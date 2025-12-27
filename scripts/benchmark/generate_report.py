#!/usr/bin/env python3
"""
Generate Benchmark Report

Aggregates benchmark results from all tests and generates a comprehensive
markdown report with charts and tables.

Usage:
    python generate_report.py --env dev
    python generate_report.py --api api_results.json --search search_results.json
    python generate_report.py --env dev --output custom_report.md
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional


class BenchmarkReportGenerator:
    """Generate comprehensive markdown benchmark reports."""

    def __init__(self, env: str = "dev"):
        """
        Initialize report generator.

        Args:
            env: Environment name (dev, test, prod)
        """
        self.env = env
        self.api_results = None
        self.search_results = None
        self.cold_start_results = None

    def load_results(self, api_path: Optional[Path] = None,
                    search_path: Optional[Path] = None,
                    cold_start_path: Optional[Path] = None):
        """
        Load benchmark results from JSON files.

        Args:
            api_path: Path to API benchmark results
            search_path: Path to search benchmark results
            cold_start_path: Path to cold start benchmark results
        """
        # Auto-discover files if not provided
        if api_path is None:
            api_path = self._find_latest_result('benchmark_api')

        if search_path is None:
            search_path = self._find_latest_result('benchmark_search')

        if cold_start_path is None:
            cold_start_path = self._find_latest_result('benchmark_cold_starts')

        # Load results
        if api_path and api_path.exists():
            with open(api_path) as f:
                self.api_results = json.load(f)
            print(f"✓ Loaded API results from {api_path}")

        if search_path and search_path.exists():
            with open(search_path) as f:
                self.search_results = json.load(f)
            print(f"✓ Loaded search results from {search_path}")

        if cold_start_path and cold_start_path.exists():
            with open(cold_start_path) as f:
                self.cold_start_results = json.load(f)
            print(f"✓ Loaded cold start results from {cold_start_path}")

    def _find_latest_result(self, prefix: str) -> Optional[Path]:
        """Find most recent result file matching prefix."""
        current_dir = Path('.')
        pattern = f"{prefix}_{self.env}_*.json"

        files = list(current_dir.glob(pattern))
        if files:
            # Sort by modification time
            latest = max(files, key=lambda p: p.stat().st_mtime)
            return latest

        return None

    def generate_report(self) -> str:
        """
        Generate comprehensive markdown report.

        Returns:
            Markdown report content
        """
        sections = []

        # Header
        sections.append(self._generate_header())

        # Executive Summary
        sections.append(self._generate_executive_summary())

        # API Benchmarks
        if self.api_results:
            sections.append(self._generate_api_section())

        # Search Benchmarks
        if self.search_results:
            sections.append(self._generate_search_section())

        # Cold Start Benchmarks
        if self.cold_start_results:
            sections.append(self._generate_cold_start_section())

        # Performance Targets
        sections.append(self._generate_targets_section())

        # Recommendations
        sections.append(self._generate_recommendations())

        # Footer
        sections.append(self._generate_footer())

        return '\n\n'.join(sections)

    def _generate_header(self) -> str:
        """Generate report header."""
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

        return f"""# Phase 5 Benchmark Report

**Environment:** `{self.env.upper()}`
**Generated:** {timestamp}
**AWS Region:** us-east-1

---
"""

    def _generate_executive_summary(self) -> str:
        """Generate executive summary section."""
        summary = "## Executive Summary\n\n"

        # Collect key metrics
        key_metrics = []

        if self.api_results and 'summary' in self.api_results:
            api_summary = self.api_results['summary']
            if 'overall_metrics' in api_summary:
                metrics = api_summary['overall_metrics']
                if 'p95_latency_ms' in metrics:
                    key_metrics.append(
                        f"- **API P95 Latency:** {metrics['p95_latency_ms']:.2f}ms"
                    )
                if 'average_success_rate' in metrics:
                    key_metrics.append(
                        f"- **API Success Rate:** {metrics['average_success_rate']:.1f}%"
                    )

        if self.search_results and 'summary' in self.search_results:
            search_summary = self.search_results['summary']
            if 'winner' in search_summary:
                if 'fastest' in search_summary['winner']:
                    fastest = search_summary['winner']['fastest']
                    key_metrics.append(
                        f"- **Fastest Search:** {fastest['method']} "
                        f"({fastest['p95_latency_ms']:.2f}ms P95)"
                    )

        if self.cold_start_results and 'summary' in self.cold_start_results:
            cold_summary = self.cold_start_results['summary']
            if 'target_compliance' in cold_summary and 'api' in cold_summary['target_compliance']:
                api_cold = cold_summary['target_compliance']['api']
                status = "✅ PASS" if api_cold['meets_target'] else "❌ FAIL"
                key_metrics.append(
                    f"- **API Cold Start:** {api_cold['mean_ms']:.2f}ms {status}"
                )

        if key_metrics:
            summary += "### Key Metrics\n\n"
            summary += '\n'.join(key_metrics)
        else:
            summary += "*No benchmark data available*"

        return summary

    def _generate_api_section(self) -> str:
        """Generate API benchmark section."""
        section = "## API Endpoint Benchmarks\n\n"

        if not self.api_results or 'endpoints' not in self.api_results:
            return section + "*No API benchmark data*"

        endpoints = self.api_results['endpoints']

        for endpoint_path, endpoint_data in endpoints.items():
            section += f"### `{endpoint_data.get('method', 'GET')} {endpoint_path}`\n\n"

            if 'concurrency_tests' in endpoint_data:
                # Create table
                section += "| Concurrency | Success Rate | RPS | Mean (ms) | Median (ms) | P95 (ms) | P99 (ms) |\n"
                section += "|-------------|--------------|-----|-----------|-------------|----------|----------|\n"

                for test in endpoint_data['concurrency_tests']:
                    latency = test.get('latency', {})
                    section += (
                        f"| {test['concurrency']} | "
                        f"{test['success_rate']:.1f}% | "
                        f"{test['requests_per_second']:.1f} | "
                        f"{latency.get('mean_ms', 0):.2f} | "
                        f"{latency.get('median_ms', 0):.2f} | "
                        f"{latency.get('p95_ms', 0):.2f} | "
                        f"{latency.get('p99_ms', 0):.2f} |\n"
                    )

                section += "\n"

        return section

    def _generate_search_section(self) -> str:
        """Generate search benchmark section."""
        section = "## Search Performance Benchmarks\n\n"

        if not self.search_results or 'search_methods' not in self.search_results:
            return section + "*No search benchmark data*"

        methods = self.search_results['search_methods']

        # Create comparison table
        section += "### Method Comparison\n\n"
        section += "| Method | Mean (ms) | Median (ms) | P95 (ms) | P99 (ms) | Success Rate |\n"
        section += "|--------|-----------|-------------|----------|----------|---------------|\n"

        for method_name, method_data in methods.items():
            latency = method_data.get('latency', {})
            section += (
                f"| {method_name.upper()} | "
                f"{latency.get('mean_ms', 0):.2f} | "
                f"{latency.get('median_ms', 0):.2f} | "
                f"{latency.get('p95_ms', 0):.2f} | "
                f"{latency.get('p99_ms', 0):.2f} | "
                f"{method_data.get('success_rate', 0):.1f}% |\n"
            )

        section += "\n"

        # Quality metrics if available
        has_quality = any('quality' in m for m in methods.values())
        if has_quality:
            section += "### Quality Metrics\n\n"
            section += "| Method | Precision@k | Recall@k | MRR |\n"
            section += "|--------|-------------|----------|-----|\n"

            for method_name, method_data in methods.items():
                if 'quality' in method_data:
                    quality = method_data['quality']
                    section += (
                        f"| {method_name.upper()} | "
                        f"{quality.get('precision_at_k', 0):.3f} | "
                        f"{quality.get('recall_at_k', 0):.3f} | "
                        f"{quality.get('mrr', 0):.3f} |\n"
                    )

            section += "\n"

        return section

    def _generate_cold_start_section(self) -> str:
        """Generate cold start benchmark section."""
        section = "## Lambda Cold Start Analysis\n\n"

        if not self.cold_start_results or 'functions' not in self.cold_start_results:
            return section + "*No cold start benchmark data*"

        functions = self.cold_start_results['functions']

        # Create table
        section += "| Function | Mean Total (ms) | Mean Init (ms) | Target | Status |\n"
        section += "|----------|-----------------|----------------|--------|---------|\n"

        for func_type, func_data in functions.items():
            if 'error' in func_data:
                section += f"| {func_type.upper()} | ERROR | - | - | ❌ |\n"
                continue

            total = func_data.get('total_duration', {})
            init = func_data.get('init_duration', {})

            mean_total = total.get('mean_ms', 0)
            mean_init = init.get('mean_ms', 0) if init else 0

            # Check target for API
            status = ""
            target = ""
            if func_type == 'api' and 'meets_target' in func_data:
                target = f"{func_data['target_ms']}ms"
                status = "✅" if func_data['meets_target'] else "❌"

            section += (
                f"| {func_type.upper()} | "
                f"{mean_total:.2f} | "
                f"{mean_init:.2f if mean_init else 'N/A'} | "
                f"{target or 'N/A'} | "
                f"{status or '-'} |\n"
            )

        section += "\n"

        return section

    def _generate_targets_section(self) -> str:
        """Generate performance targets comparison."""
        section = "## Performance Targets\n\n"

        section += "| Metric | Target | Actual | Status |\n"
        section += "|--------|--------|--------|--------|\n"

        # API Latency target: < 500ms P95
        if self.api_results and 'summary' in self.api_results:
            api_summary = self.api_results['summary']
            if 'overall_metrics' in api_summary:
                p95 = api_summary['overall_metrics'].get('p95_latency_ms', 0)
                target = 500
                status = "✅ PASS" if p95 < target else "❌ FAIL"
                section += f"| API P95 Latency | < {target}ms | {p95:.2f}ms | {status} |\n"

        # Search Latency target: < 300ms P95
        if self.search_results and 'search_methods' in self.search_results:
            methods = self.search_results['search_methods']
            if 'hybrid' in methods:
                hybrid = methods['hybrid']
                p95 = hybrid.get('latency', {}).get('p95_ms', 0)
                target = 300
                status = "✅ PASS" if p95 < target else "❌ FAIL"
                section += f"| Search P95 Latency | < {target}ms | {p95:.2f}ms | {status} |\n"

        # Cold Start target: < 3s
        if self.cold_start_results and 'summary' in self.cold_start_results:
            summary = self.cold_start_results['summary']
            if 'target_compliance' in summary and 'api' in summary['target_compliance']:
                api_cold = summary['target_compliance']['api']
                actual = api_cold['mean_ms']
                target = api_cold['target_ms']
                status = "✅ PASS" if api_cold['meets_target'] else "❌ FAIL"
                section += f"| API Cold Start | < {target}ms | {actual:.2f}ms | {status} |\n"

        section += "\n"

        return section

    def _generate_recommendations(self) -> str:
        """Generate recommendations based on results."""
        section = "## Recommendations\n\n"

        recommendations = []

        # Check API latency
        if self.api_results and 'summary' in self.api_results:
            api_summary = self.api_results['summary']
            if 'overall_metrics' in api_summary:
                p95 = api_summary['overall_metrics'].get('p95_latency_ms', 0)
                if p95 > 500:
                    recommendations.append(
                        "- ⚠️ **API Latency:** P95 exceeds 500ms target. Consider:\n"
                        "  - Increasing Lambda memory allocation\n"
                        "  - Adding database connection pooling\n"
                        "  - Implementing caching for frequent queries"
                    )

        # Check cold starts
        if self.cold_start_results and 'summary' in self.cold_start_results:
            summary = self.cold_start_results['summary']
            if 'target_compliance' in summary and 'api' in summary['target_compliance']:
                api_cold = summary['target_compliance']['api']
                if not api_cold['meets_target']:
                    recommendations.append(
                        "- ⚠️ **Cold Starts:** API Lambda exceeds 3s target. Consider:\n"
                        "  - Reducing Docker image size\n"
                        "  - Using Lambda layers for dependencies\n"
                        "  - Implementing provisioned concurrency for production"
                    )

        # Check search quality
        if self.search_results and 'search_methods' in self.search_results:
            methods = self.search_results['search_methods']
            if 'hybrid' in methods and 'quality' in methods['hybrid']:
                precision = methods['hybrid']['quality'].get('precision_at_k', 0)
                if precision < 0.5:
                    recommendations.append(
                        "- ⚠️ **Search Quality:** Precision@k is low. Consider:\n"
                        "  - Tuning hybrid search weights\n"
                        "  - Improving embedding quality\n"
                        "  - Adding query expansion"
                    )

        if recommendations:
            section += '\n\n'.join(recommendations)
        else:
            section += "✅ All performance targets met. No immediate actions required."

        return section

    def _generate_footer(self) -> str:
        """Generate report footer."""
        return """---

## Appendix

### Test Environment

- **AWS Region:** us-east-1
- **Lambda Runtime:** Python 3.12
- **Database:** PostgreSQL with pgvector
- **Vector Store:** PostgreSQL pgvector
- **Full-text Search:** PostgreSQL tsvector

### Data Sources

"""

    def save_report(self, output_path: Optional[Path] = None) -> Path:
        """
        Generate and save report.

        Args:
            output_path: Output file path

        Returns:
            Path to saved report
        """
        if output_path is None:
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            reports_dir = Path('/workspaces/collections-local/reports')
            reports_dir.mkdir(exist_ok=True)
            output_path = reports_dir / f"phase5-benchmark-{self.env}-{timestamp}.md"

        # Generate report
        report_content = self.generate_report()

        # Save to file
        with open(output_path, 'w') as f:
            f.write(report_content)

        print(f"\n✅ Report saved to: {output_path}")

        return output_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Generate benchmark report')
    parser.add_argument('--env', default='dev', help='Environment (dev/test/prod)')
    parser.add_argument('--api', help='Path to API benchmark results JSON')
    parser.add_argument('--search', help='Path to search benchmark results JSON')
    parser.add_argument('--cold-start', help='Path to cold start benchmark results JSON')
    parser.add_argument('--output', help='Output markdown file path')

    args = parser.parse_args()

    # Create generator
    generator = BenchmarkReportGenerator(env=args.env)

    # Load results
    api_path = Path(args.api) if args.api else None
    search_path = Path(args.search) if args.search else None
    cold_start_path = Path(args.cold_start) if args.cold_start else None

    generator.load_results(api_path, search_path, cold_start_path)

    # Generate and save report
    output_path = Path(args.output) if args.output else None
    report_path = generator.save_report(output_path)

    # Print preview
    print("\n" + "="*60)
    print("REPORT PREVIEW")
    print("="*60)

    # Read first few lines
    with open(report_path) as f:
        lines = f.readlines()[:30]
        print(''.join(lines))

    print(f"\n... (see {report_path} for full report)")


if __name__ == '__main__':
    main()
