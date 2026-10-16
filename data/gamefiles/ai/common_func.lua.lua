REGISTER_GOAL(GOAL_COMMON_Wait, "Wait")
REGISTER_GOAL(GOAL_COMMON_Stay, "Stay")
REGISTER_GOAL(GOAL_COMMON_MoveToSomewhere, "MoveToSomewhere")
REGISTER_GOAL(GOAL_COMMON_Guard, "Guard")
REGISTER_GOAL(GOAL_COMMON_SidewayMove, "SidewayMove")
REGISTER_GOAL(GOAL_COMMON_KeepDist, "KeepDist")
REGISTER_GOAL(GOAL_COMMON_BackToHome, "BackToHome")
REGISTER_GOAL(GOAL_COMMON_SpinStep, "SpinStep")
REGISTER_GOAL(GOAL_COMMON_LeaveTarget, "LeaveTarget")
REGISTER_GOAL(GOAL_COMMON_ApproachStep, "ApproachStep")
REGISTER_GOAL(GOAL_COMMON_Parry, "Parry")
function _COMMON_GetEzStateAnimId(ai, animTblParamId)
    ret = {}
    local i = 1
    local local0 = 1
    for local1 = 1 - local0, 30, local0 do
        ret[local1] = ai:GetEzStateAnimId(animTblParamId, local1 - 1)
    end
    return ret
end

function _COMMON_GetMinDist(ai, animTblParamId)
    ret = {}
    local i = 1
    local local0 = 1
    for local1 = 1 - local0, 30, local0 do
        ret[local1] = ai:GetMinDist(animTblParamId, local1 - 1)
    end
    return ret
end

function _COMMON_GetMaxDist(ai, animTblParamId)
    ret = {}
    local i = 0
    local local0 = 1
    for local1 = 0 - local0, 29, local0 do
        ret[local1] = ai:GetMaxDist(animTblParamId, local1 - 1)
    end
    return ret
end

function _COMMON_GetAtkDistType(ai, animTblParamId)
    ret = {}
    local i = 1
    local local0 = 1
    local local1 = 1 - local0
    goto basicblock_12:
end

function _COMMON_GetOddsParam(ai, oddsParamId)
    ret = {}
    local oddsParamOffset = ai:GetOddsParamIdOffset(100)
    local i = 0
    local local0 = 1
    for local1 = 0 - local0, 99, local0 do
        ret[local1] = ai:GetOddsParam(oddsParamOffset + oddsParamId, local1)
    end
    return ret
end

function _COMMON_MulOddsXWeight(inoutAct, inFinal)
    local i = 0
    local bInitFinal = true
    if table.getn(inFinal) == 0 then
        bInitFinal = false
    end
    local totalActVal = 0
    local maxActVal = 0
    local local0 = 1
    for local1 = 0 - local0, 99, local0 do
        if bInitFinal == false then
            inFinal[local1] = 1
        end
        inoutAct[local1] = inoutAct[local1] * inFinal[local1]
        if inoutAct[local1] < 0 then
            inoutAct[local1] = 0
        else
            inoutAct[local1] = inoutAct[local1] + totalActVal
            totalActVal = inoutAct[local1]
            if maxActVal < inoutAct[local1] then
                maxActVal = inoutAct[local1]
            end
        end
    end
    return maxActVal
end

function _COMMON_MulWeightParam(ai, final, oddsParamId)
    local zeroTbl = false
    if table.getn(final) == 0 then
        zeroTbl = true
    end
    local oddsParamOffset = ai:GetOddsParamIdOffset(100)
    local i = 0
    local local0 = 1
    for local1 = 0 - local0, 99, local0 do
        if zeroTbl then
            final[local1] = 1
        end
        final[local1] = final[local1] * ai:GetOddsParam(oddsParamOffset + oddsParamId, local1)
    end
    return 
end

return 
