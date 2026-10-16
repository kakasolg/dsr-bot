REGISTER_GOAL(GOAL_COMMON_GuardBreakTunable, "GuardBreakTunable")
REGISTER_DBG_GOAL_PARAM(GOAL_COMMON_GuardBreakTunable, 0, "EzStateID", 0)
REGISTER_DBG_GOAL_PARAM(GOAL_COMMON_GuardBreakTunable, 1, "攻撃対象", 0)
REGISTER_DBG_GOAL_PARAM(GOAL_COMMON_GuardBreakTunable, 2, "成功距離", 0)
REGISTER_DBG_GOAL_PARAM(GOAL_COMMON_GuardBreakTunable, 3, "攻撃前旋回時間【秒】", 0)
REGISTER_DBG_GOAL_PARAM(GOAL_COMMON_GuardBreakTunable, 4, "正面判定角度【度】", 0)
REGISTER_DBG_GOAL_PARAM(GOAL_COMMON_GuardBreakTunable, 5, "上攻撃角度", 0)
REGISTER_DBG_GOAL_PARAM(GOAL_COMMON_GuardBreakTunable, 6, "下攻撃角度", 0)
REGISTER_GOAL_NO_UPDATE(GOAL_COMMON_GuardBreakTunable, 1)
function GuardBreakTunable_Activate(ai, goal)
    local life = goal:GetLife()
    local behaviorNo = goal:GetParam(0)
    local attackTarget = goal:GetParam(1)
    local distType = goal:GetParam(2)
    local successAngle = 90
    local turnTime = goal:GetParam(3)
    local turnFaceAngle = goal:GetParam(4)
    if turnTime < 0 then
        turnTime = 1.5
    end
    if turnFaceAngle < 0 then
        turnFaceAngle = 20
    end
    local isComboAttack = true
    local isMoveCancel = true
    local isGaurdBreakAtk = true
    local isTurn = false
    local angleUpAtt = goal:GetParam(5)
    local angleDownAtt = goal:GetParam(6)
    goal:AddSubGoal(GOAL_COMMON_CommonAttack, life, behaviorNo, attackTarget, distType, successAngle, turnTime, turnFaceAngle, isComboAttack, isMoveCancel, isGaurdBreakAtk, isTurn, angleUpAtt, angleDownAtt)
    return 
end

function GuardBreakTunable_Update(ai, goal)
    return GOAL_RESULT_Continue
end

function GuardBreakTunable_Terminate(ai, goal)
    return 
end

REGISTER_GOAL_NO_INTERUPT(GOAL_COMMON_GuardBreakTunable, true)
function GuardBreakTunable_Interupt(ai, goal)
    return false
end

return 
