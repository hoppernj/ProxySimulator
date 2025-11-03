# Minimized SpotProxy

## Set up

$ >> pip3 install -r requirements.txt

$ >> python manage.py makemigrations

$ >> python manage.py migrate
 
## Run

$ >> PYTHONPATH=. python scripts/run_simulation_minimal.py --distributor strict (**You can replace "strict" with "kind" to simulate kind distribution**)

Make sure you are in "Proxy_Simulator/Minimized_SpotProxy_Version" when you run all of the above commands!


## Scoring Equations:

<p>
RbridgeScore(P, C) = α<sub>1</sub> · U − α<sub>2</sub> · R − α<sub>3</sub> · B − α<sub>5</sub> · L
</p>

Where:
- U = proxy usage count
- R = number of proxy requests made by the client
- B = number of known blocked proxies encountered by the client
- L = location penalty (currently fixed as 1)
- α₁ through α₅ = tunable weights

---

<p>
ZigZagScore(C, t) = w<sub>1</sub> · R + w<sub>2</sub> · S + w<sub>3</sub> · (1 − D) + w<sub>4</sub> · B
</p>


Where:
- R = repeat assignment ratio
- S = short-window reuse ratio
- D = proxy diversity (unique/total)
- B = known blocked proxy rate
- w1–w4 = tunable weights

