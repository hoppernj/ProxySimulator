import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
runseed = int.from_bytes(os.urandom(8))
random.seed(runseed)

import shutil
shutil.copyfile('db.sqlite3',f'db.{runseed}.sqlite3')
import config.settings
config.settings.DATABASES['default']['NAME'] = f'db.{runseed}.sqlite3'

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import argparse

from django.db.models import F
from assignments.models import User, Proxy, Assignment, Block
from config_basic import Parameters as P, KIND_PROFILE, STRICT_PROFILE



def run_simulation(duration=P.BIRTH_PERIOD + P.SIMULATION_DURATION,
                   env_type="dynamic",
                   distributor_type='strict', 
                   censor_type="greedy",
                   collateral=False,
                   clist = None,
                   wlist = None):
    Proxy.objects.all().delete()
    User.objects.all().delete()
    Assignment.objects.all().delete()
    Block.objects.all().delete()
    import Distributor
    from Environment import Environment, EphemeralEnv, Collateral, MultiNetwork, EphemeralMultiNet
    from Censor import OptimalCensor, TargetedCensor, AggressiveCensor, GreedyOptimalCensor, ConservativeCensor, ZigZagCensor, ProfileCensor, MultiCensor, NullCensor

    multi = censor_type == 'multi'
    def censor_from_type(cty):
        match cty:
            case 'targeted': return TargetedCensor()
            case 'aggressive': return AggressiveCensor()
            case 'conservative': return ConservativeCensor(fraction=P.CONSERVATIVE_FRACTION)
            case 'greedy': return GreedyOptimalCensor(distributor=dist)
            case 'optimal': return OptimalCensor(distributor=dist)
            case 'zigzag': return ZigZagCensor(P.ZIGZAG_ROUNDS)
            case 'profile': return ProfileCensor()
            case 'null': return NullCensor()
        return None

    match distributor_type:
        case 'rbridge': dist = Distributor.RBridge(env=None)
        case 'snowflake': dist = Distributor.Snowflake(env=None)
        case 'kind': dist = Distributor.DeferredAcceptance(KIND_PROFILE)
        case 'strict': dist = Distributor.DeferredAcceptance(STRICT_PROFILE)
        case 'antizag': dist = Distributor.AntiZigZag(STRICT_PROFILE,P.ANTIZAG_WEIGHT)

    if not multi: censor = censor_from_type(censor_type)
    else:
        cmap = {}
        for i in range(len(clist)):
            net = str(i)
            cmap[net] = censor_from_type(clist[i])
        censor = MultiCensor(cmap)

    match env_type:
        case 'ephemeral': env = EphemeralMultiNet(censor,wlist) if multi else EphemeralEnv(censor) 
        case 'dynamic': env = MultiNetwork(censor,wlist) if multi else Environment(censor)
    if collateral: env = Collateral(env)

    env.set_seed(runseed)
    dist.set_env(env)
    censor.set_env(env)
    blocked_users = []
    for step in range(duration):
        env.createNewProxies(step)
        new_users = env.newUsers(step)
        blocked_users += new_users
        for block in censor.run(step):
            user_ids = env.block(block,step)
            for user_id in user_ids:
                user = User.objects.get(id=user_id)
                if user_id not in env.user_wait_start and env.user_is_blocked(user):
                    env.user_wait_start[user_id] = step 
                blocked_users.append(user)
        dist.request_new_proxies(blocked_users,step)
        env.logStep(step)
        env.removeUsers(step)
        env.removeProxies(step)
        dist.update_users(step)
        dist.update_proxies(step)

        blocked_users = []
        for user_id in env.user_wait_start:
            user = User.objects.get(id=user_id)
            if env.user_is_blocked(user) and user.is_active: blocked_users.append(user)

    env.close_files()
    print("Simulation complete!")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--distributor", choices=["kind", "strict", "snowflake", "rbridge", "antizag"], default="strict")
    parser.add_argument("--env", choices=["dynamic", "ephemeral"], default="dynamic")
    parser.add_argument("--censor", choices=["optimal", "targeted", "aggressive", "greedy", "zigzag", "conservative", "profile","null"], default="aggressive",nargs='*')
    parser.add_argument("--weights", nargs='*', type=float)
    parser.add_argument("--collateral",action="store_true")
    parser.add_argument("--config",default=None)
    return parser.parse_args()

def dump_params(f):
    import json
    p_dict = {k:v for k,v in P.__dict__.items() if k[0] != '_'}
    json.dump(p_dict,f,indent=1)

def load_params(fname):
    import json
    with open(fname,"r") as f:
        params = json.load(f)
    for k in params.keys():
        if k in P.__dict__:
            exec(f"P.{k} = {params[k]}")

if __name__ == "__main__":
    args = parse_args()
    if args.config:
        load_params(args.config)

    with open(f"config.{runseed}.json","w") as f:
        dump_params(f)
        print(f"\n{args}",file=f)

    ctype = args.censor[0]
    if args.weights and len(args.weights) != len(args.censor):
        printf("Must have same number of weights as censors!")
        exit(-1)
    if len(args.censor) > 1: 
        ctype = 'multi'
        if not args.weights:
            args.weights = [1]*len(args.censor)

    run_simulation(duration=P.BIRTH_PERIOD+P.SIMULATION_DURATION,
                   distributor_type=args.distributor,
                   env_type=args.env,
                   censor_type=ctype,
                   collateral=args.collateral,
                   clist=args.censor if ctype=='multi' else None,
                   wlist=args.weights if args.weights else None)


