This demo shows a simple arbitrageur strategy to take advantage the funding fee and negative slippage.

Strategy Procedures:

1. When pool's net volume is $N$, the arbitrageur trades $-N/2$ volume to bring the pool's net volume from $N$ to $N/2$.
2. By doing this, the arbitrageur immediately gain negative slippage profit due to reduce pool's net volume. After trading, the pool's net volume direction remains the same, which is the opposite of arbitrageur's position, and the arbitrageur will have a negative funding accrued with time, which means as long as the position remains unchanged, the arbitrageur is now collecting funding.
3. To eliminate the price risk, the arbitrageur can hedge his position at other place, for example, a cefi exchange like Binance. By doing this, the arbitrageur will have no risk exposure to price change, while at the mean time, he can still keep collecting funding fee.
4. When other's open/close positions, the net volume of the pool changes, the arbitrageur needs to adjust his position and hedging accordingly.
