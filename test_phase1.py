from src.analysis.utils.fund_mapping import FundIndexMapper
from src.data_sources.index_valuation import IndexValuationSource


def main() -> None:
    fund_name = "易方达沪深300ETF联接A"
    index_code = FundIndexMapper.guess_index_code(fund_name)
    print(f"基金: {fund_name} -> 映射指数: {index_code}")

    if index_code:
        valuation = IndexValuationSource.fetch_index_valuation(index_code)
        print("估值数据:", valuation)


if __name__ == "__main__":
    main()

