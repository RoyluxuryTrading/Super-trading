// MLq4_librery_V6.mq4  —  Version 6 (Robustness: retry, duplicates, restart safety)
// © MLq4 librery

#property copyright "© MLq4 librery"
#property link      "MLq4 librery"
#property version   "6.00"
#property strict
#property description "MLq4 librery – V6 adds SafeOrderSend, duplicate prevention, restart safety"

// ======== Inputs ========
extern string   EA_Name         = "MLq4_librery_V6";
extern int      Magic           = 1111111;

// Trade filters / logic
extern int      Max_Spread      = 30;     // in points
extern int      StepPoints      = 50;     // pending distance from market, in points
extern int      SL_Points       = 500;    // fixed SL in points (also used for risk sizing)
extern int      TP_Points       = 900;    // fixed TP in points
extern double   SarPeriod       = 0.56;   // SAR accel
extern double   SarAccel        = 0.20;   // SAR max accel
extern int      Trail_Points    = 300;    // classic trailing in points
extern int      MinVolume       = 2;      // ignore first tick of bar if Volume[0] < MinVolume
extern bool     OneOrderPerSide = true;   // prevent stacking same-side pendings

// Sessions + cooldown (server time)
extern bool     UseSessions     = true;
extern int      LondonStart     = 8;
extern int      LondonEnd       = 12;     // exclusive
extern int      NYStart         = 14;
extern int      NYEnd           = 20;     // exclusive
extern int      CooldownMin     = 10;     // minutes between same-side planned orders

// Risk-based lot sizing + Equity guard (from V3)
extern bool     UseRiskSizing   = true;   // if false -> uses FixedLots
extern double   FixedLots       = 0.05;
extern double   RiskPercent     = 1.0;    // % of balance per trade
extern double   MaxDrawdownPct  = 35.0;   // stop trading if equity drawdown >= this %

// Higher-Timeframe Trend Filter (from V4)
extern bool     UseHTFTrend     = true;          // enable/disable HTF filter
extern int      HTF_EMA_Period  = 200;           // default 200 EMA
extern int      HTF_TF          = PERIOD_M15;     // higher timeframe (e.g., PERIOD_H1 or PERIOD_H4)

// BE + Partial + Time Exit (from V5)
extern bool     UseBreakEven       = true;
extern int      BE_TriggerPoints   = 400;
extern int      BE_LockPoints      = 50;
extern bool     UsePartialClose    = true;
extern double   PartialClosePct    = 0.50;
extern int      TimeExitMin        = 180;

// ======== NEW (V6): Robustness toggles ========
extern int      Slippage           = 3;    // max price deviation for orders
extern int      RetryMillis        = 500;  // delay between retries (ms)
extern int      MaxRetries         = 3;    // retries for OrderSend/Modify/Close
extern int      DuplicateTolerancePoints = 5; // avoid placing near-identical pendings

// ======== Globals ========
datetime lastBuyPlan  = 0;
datetime lastSellPlan = 0;
datetime G_LastBar    = 0;

// ======== Lifecycle ========
int init()
{
   G_LastBar = Time[0];
   // On attach/restart, ensure open orders have proper SL/TP
   EnsureStopsForOpenPositions();
   // Clean any invalid/expired pendings
   DeleteInvalidPendings();
   return(0);
}
int deinit(){ return(0); }

int start()
{
   // New-bar housekeeping (run once per bar to avoid tick spam)
   if(Time[0] != G_LastBar)
   {
      G_LastBar = Time[0];
      RefreshRates();
      DeleteInvalidPendings();
      EnsureStopsForOpenPositions();
   }

   // --- Equity guard: stop trading if drawdown exceeded
   if(MaxDrawdownPct > 0.0)
   {
      double eq  = AccountEquity();
      double bal = AccountBalance();
      if(bal > 0)
      {
         double pct = (eq / bal) * 100.0;
         if(pct < (100.0 - MaxDrawdownPct)) return(0); // halt entries
      }
   }

   if(!SpreadOk())  return(0);
   if(!VolumeOk())  return(0);

   // Direction: SAR bias + Bands context
   double sar   = iSAR(NULL,0,SarPeriod,SarAccel,0);
   double bbTop = iBands(NULL,0,20,2,0,PRICE_CLOSE,MODE_UPPER,0);
   double bbBot = iBands(NULL,0,20,2,0,PRICE_CLOSE,MODE_LOWER,0);

   bool biasBuy  = (Close[0] > sar) && (Ask < bbTop);
   bool biasSell = (Close[0] < sar) && (Bid  > bbBot);

   // Sessions gate
   if(UseSessions && !InTradingWindow())
   {
      biasBuy  = false;
      biasSell = false;
   }

   // HTF EMA trend filter
   if(UseHTFTrend && HTF_EMA_Period > 0)
   {
      double emaHTF = iMA(NULL, HTF_TF, HTF_EMA_Period, 0, MODE_EMA, PRICE_CLOSE, 0);
      if(emaHTF > 0)
      {
         if(biasBuy  && Close[0] < emaHTF) biasBuy  = false; // only buy above EMA
         if(biasSell && Close[0] > emaHTF) biasSell = false; // only sell below EMA
      }
   }

   // Manage existing positions (includes BE/Partial/TimeExit)
   ManageOpenPositions();
   // Also prune far-crossed pendings
   DeleteFarPendings();

   // Entries via pending stops (reduce slippage) + duplicate prevention + cooldown
   if(biasBuy && (!OneOrderPerSide || !HasPending(OP_BUYSTOP)) && IsCooldownOk(true))
   {
      double price = NormalizeDouble(Ask + StepPoints*Point,Digits);
      if(!DuplicatePendingExists(OP_BUYSTOP, price, DuplicateTolerancePoints))
      {
         PlaceBuyStop(price);
         lastBuyPlan = TimeCurrent();
      }
   }

   if(biasSell && (!OneOrderPerSide || !HasPending(OP_SELLSTOP)) && IsCooldownOk(false))
   {
      double price = NormalizeDouble(Bid - StepPoints*Point,Digits);
      if(!DuplicatePendingExists(OP_SELLSTOP, price, DuplicateTolerancePoints))
      {
         PlaceSellStop(price);
         lastSellPlan = TimeCurrent();
      }
   }

   return(0);
}

// ======== Helpers ========
bool SpreadOk()
{
   double spr = NormalizeDouble((Ask-Bid)/Point,Digits);
   return (spr <= Max_Spread);
}
bool VolumeOk(){ return (Volume[0] >= MinVolume); }

bool HasPending(int type)
{
   for(int i=OrdersTotal()-1;i>=0;i--)
      if(OrderSelect(i,SELECT_BY_POS,MODE_TRADES))
         if(OrderSymbol()==Symbol() && OrderMagicNumber()==Magic && OrderType()==type)
            return(true);
   return(false);
}

// Detects a pending of the same type near target price to avoid duplicates
bool DuplicatePendingExists(int type, double targetPrice, int tolPts)
{
   double tol = tolPts * Point;
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      if(!OrderSelect(i,SELECT_BY_POS,MODE_TRADES)) continue;
      if(OrderSymbol()!=Symbol() || OrderMagicNumber()!=Magic) continue;
      if(OrderType()!=type) continue;

      if(MathAbs(OrderOpenPrice() - targetPrice) <= tol)
         return(true);
   }
   return(false);
}

void DeleteFarPendings()
{
   // If price moved through a pending by > 2*Step, remove and await re-eval
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      if(!OrderSelect(i,SELECT_BY_POS,MODE_TRADES)) continue;
      if(OrderSymbol()!=Symbol() || OrderMagicNumber()!=Magic) continue;

      if(OrderType()==OP_BUYSTOP && Bid + 2*StepPoints*Point > OrderOpenPrice())
         SafeOrderDelete(OrderTicket());

      if(OrderType()==OP_SELLSTOP && Ask - 2*StepPoints*Point < OrderOpenPrice())
         SafeOrderDelete(OrderTicket());
   }
}

// Extra invalid/expired checks each bar and on attach
void DeleteInvalidPendings()
{
   datetime now = TimeCurrent();
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      if(!OrderSelect(i,SELECT_BY_POS,MODE_TRADES)) continue;
      if(OrderSymbol()!=Symbol() || OrderMagicNumber()!=Magic) continue;

      if(OrderType()==OP_BUYSTOP || OrderType()==OP_SELLSTOP)
      {
         // Expired?
         if(OrderExpiration()>0 && OrderExpiration() < now)
            SafeOrderDelete(OrderTicket());

         // Zero/NaN price safety
         if(OrderOpenPrice() <= 0)
            SafeOrderDelete(OrderTicket());
      }
   }
}

// Reattach SL/TP for open market positions if missing (restart safety)
void EnsureStopsForOpenPositions()
{
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      if(!OrderSelect(i,SELECT_BY_POS,MODE_TRADES)) continue;
      if(OrderSymbol()!=Symbol() || OrderMagicNumber()!=Magic) continue;

      int type = OrderType();
      if(type!=OP_BUY && type!=OP_SELL) continue;

      double open = OrderOpenPrice();
      double sl = OrderStopLoss();
      double tp = OrderTakeProfit();

      if(type==OP_BUY)
      {
         double wantSL = NormalizeDouble(open - SL_Points*Point,Digits);
         double wantTP = NormalizeDouble(open + TP_Points*Point,Digits);
         if((sl<=0 && SL_Points>0) || (tp<=0 && TP_Points>0))
            SafeOrderModify(OrderTicket(), open, (SL_Points>0?wantSL:sl), (TP_Points>0?wantTP:tp), 0, clrBlue);
      }
      if(type==OP_SELL)
      {
         double wantSL = NormalizeDouble(open + SL_Points*Point,Digits);
         double wantTP = NormalizeDouble(open - TP_Points*Point,Digits);
         if((sl<=0 && SL_Points>0) || (tp<=0 && TP_Points>0))
            SafeOrderModify(OrderTicket(), open, (SL_Points>0?wantSL:sl), (TP_Points>0?wantTP:tp), 0, clrRed);
      }
   }
}

// ======== Order placement (uses retry wrapper) ========
void PlaceBuyStop(double price)
{
   double sl  = NormalizeDouble(price - SL_Points*Point,Digits);
   double tp  = NormalizeDouble(price + TP_Points*Point,Digits);
   double lot = SelectLotByRisk(SL_Points);

   if(AccountFreeMarginCheck(Symbol(),OP_BUYSTOP,lot)<=0) return;

   SafeOrderSend(Symbol(), OP_BUYSTOP, lot, price, Slippage, sl, tp, EA_Name, Magic, 0, clrBlue);
}
void PlaceSellStop(double price)
{
   double sl  = NormalizeDouble(price + SL_Points*Point,Digits);
   double tp  = NormalizeDouble(price - TP_Points*Point,Digits);
   double lot = SelectLotByRisk(SL_Points);

   if(AccountFreeMarginCheck(Symbol(),OP_SELLSTOP,lot)<=0) return;

   SafeOrderSend(Symbol(), OP_SELLSTOP, lot, price, Slippage, sl, tp, EA_Name, Magic, 0, clrRed);
}

// ======== Lot sizing ========
double SelectLotByRisk(int slPoints)
{
   if(!UseRiskSizing) return ClampLot(FixedLots);

   double lot = CalcRiskLot(slPoints);
   return ClampLot(lot);
}
double CalcRiskLot(int slPoints)
{
   double tickSize  = MarketInfo(Symbol(), MODE_TICKSIZE);
   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   if(tickSize <= 0.0 || tickValue <= 0.0 || slPoints <= 0)
      return ClampLot(FixedLots);

   double priceDist = slPoints * Point;
   double ticks     = priceDist / tickSize;
   double perLotRisk= ticks * tickValue;

   double riskMoney = AccountBalance() * (RiskPercent/100.0);
   if(perLotRisk <= 0.0) return ClampLot(FixedLots);

   double lots = riskMoney / perLotRisk;
   return lots;
}
double ClampLot(double lot)
{
   double step = MarketInfo(Symbol(),MODE_LOTSTEP);
   double minL = MarketInfo(Symbol(),MODE_MINLOT);
   double maxL = MarketInfo(Symbol(),MODE_MAXLOT);

   if(step<=0) step=0.01;
   lot = MathFloor(lot/step)*step;

   if(lot<minL) lot=minL;
   if(lot>maxL) lot=maxL;

   return(NormalizeDouble(lot,2));
}

// ======== Trade management (V5 carried forward) ========
void ManageOpenPositions()
{
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      if(!OrderSelect(i,SELECT_BY_POS,MODE_TRADES)) continue;
      if(OrderSymbol()!=Symbol() || OrderMagicNumber()!=Magic) continue;

      int    type     = OrderType();
      double open     = OrderOpenPrice();
      double lots     = OrderLots();
      double minLot   = MarketInfo(Symbol(),MODE_MINLOT);
      double stepLot  = MarketInfo(Symbol(),MODE_LOTSTEP);
      if(stepLot<=0) stepLot=0.01;

      // --- BUY management
      if(type==OP_BUY)
      {
         // Classic trailing
         if(Trail_Points>0)
         {
            double newSL = NormalizeDouble(Bid - Trail_Points*Point,Digits);
            if((OrderStopLoss()==0) || (newSL>OrderStopLoss()))
               SafeOrderModify(OrderTicket(),open,newSL,OrderTakeProfit(),0,clrBlue);
         }

         // Break-even
         if(UseBreakEven && BE_TriggerPoints>0)
         {
            double profitPts = (Bid - open)/Point;
            if(profitPts >= BE_TriggerPoints)
            {
               double beSL = NormalizeDouble(open + BE_LockPoints*Point,Digits);
               if(OrderStopLoss() < beSL)
                  SafeOrderModify(OrderTicket(),open,beSL,OrderTakeProfit(),0,clrBlue);
            }
         }

         // Partial close
         if(UsePartialClose && PartialClosePct>0.0 && PartialClosePct<1.0)
         {
            double triggerPts = MathMax(TP_Points/2.0, BE_TriggerPoints);
            double profitPts  = (Bid - open)/Point;
            if(profitPts >= triggerPts)
            {
               double closeLots = NormalizeDouble(lots * PartialClosePct, 2);
               if(closeLots >= minLot && closeLots < lots)
                  SafeOrderClose(OrderTicket(), closeLots, Bid, Slippage, clrBlue);
            }
         }

         // Time-based exit
         if(TimeExitMin>0)
            if((TimeCurrent()-OrderOpenTime()) >= TimeExitMin*60)
               SafeOrderClose(OrderTicket(), lots, Bid, Slippage, clrBlue);
      }

      // --- SELL management
      if(type==OP_SELL)
      {
         if(Trail_Points>0)
         {
            double newSL = NormalizeDouble(Ask + Trail_Points*Point,Digits);
            if((OrderStopLoss()==0) || (newSL<OrderStopLoss()))
               SafeOrderModify(OrderTicket(),open,newSL,OrderTakeProfit(),0,clrRed);
         }

         if(UseBreakEven && BE_TriggerPoints>0)
         {
            double profitPts = (open - Ask)/Point;
            if(profitPts >= BE_TriggerPoints)
            {
               double beSL = NormalizeDouble(open - BE_LockPoints*Point,Digits);
               if(OrderStopLoss()==0 || OrderStopLoss()>beSL)
                  SafeOrderModify(OrderTicket(),open,beSL,OrderTakeProfit(),0,clrRed);
            }
         }

         if(UsePartialClose && PartialClosePct>0.0 && PartialClosePct<1.0)
         {
            double triggerPts = MathMax(TP_Points/2.0, BE_TriggerPoints);
            double profitPts  = (open - Ask)/Point;
            if(profitPts >= triggerPts)
            {
               double closeLots = NormalizeDouble(lots * PartialClosePct, 2);
               if(closeLots >= minLot && closeLots < lots)
                  SafeOrderClose(OrderTicket(), closeLots, Ask, Slippage, clrRed);
            }
         }

         if(TimeExitMin>0)
            if((TimeCurrent()-OrderOpenTime()) >= TimeExitMin*60)
               SafeOrderClose(OrderTicket(), lots, Ask, Slippage, clrRed);
      }
   }
}

// ======== Safe wrappers with retry ========
bool SafeOrderSend(string sym,int type,double lot,double price,int slip,double sl,double tp,string cmt,int magic,datetime exp,color clr)
{
   for(int r=0;r<MaxRetries;r++)
   {
      RefreshRates();
      int tk = OrderSend(sym,type,lot,price,slip,sl,tp,cmt,magic,exp,clr);
      if(tk>0) return(true);
      Sleep(RetryMillis);
   }
   return(false);
}
bool SafeOrderModify(int ticket,double price,double sl,double tp,datetime exp,color clr)
{
   for(int r=0;r<MaxRetries;r++)
   {
      RefreshRates();
      if(OrderModify(ticket,price,sl,tp,exp,clr)) return(true);
      Sleep(RetryMillis);
   }
   return(false);
}
bool SafeOrderClose(int ticket,double lots,double price,int slip,color clr)
{
   for(int r=0;r<MaxRetries;r++)
   {
      RefreshRates();
      if(OrderClose(ticket,lots,price,slip,clr)) return(true);
      Sleep(RetryMillis);
   }
   return(false);
}
bool SafeOrderDelete(int ticket)
{
   for(int r=0;r<MaxRetries;r++)
   {
      if(OrderDelete(ticket)) return(true);
      Sleep(RetryMillis);
   }
   return(false);
}

// ---------- Utilities (V2+) ----------
bool InTradingWindow()
{
   // Uses server/broker time from TimeCurrent(); adjust hours via inputs if needed.
   int h = TimeHour(TimeCurrent());
   bool london = (h >= LondonStart && h < LondonEnd);
   bool ny     = (h >= NYStart     && h < NYEnd);
   return (london || ny);
}

bool IsCooldownOk(bool buySide)
{
   if(CooldownMin<=0) return true;
   datetime last = buySide ? lastBuyPlan : lastSellPlan;
   if(last==0) return true;
   return (TimeCurrent() - last) >= CooldownMin*60;
}

