//+------------------------------------------------------------------+
//|                                      Super-trading-bot-V7.mq4   |
//|                  Clean XAUUSD scalper based on SAR + Bands      |
//|                  Inspired by your previous V6 logic             |
//+------------------------------------------------------------------+
#property copyright "MIT"
#property version   "7.00"
#property strict

//--- Inputs (aligned with your old EA interface)
extern double Sar_period   = 0.56;   // SAR step (acceleration)
extern int    Step         = 25;     // pending distance in points
extern int    Acceleration = 9;      // used as a generic filter factor (seconds / slope filter)
extern int    TrailingStop = 25;     // trailing stop in points
extern int    StopLoss     = 530;    // SL in points
extern double Lots         = 0.05;   // base lot size
extern int    Max_Spread   = 20;     // max spread in points
extern int    Magic        = 1111111;

//--- Internal constants / settings
int    Slippage           = 3;       // max price deviation
int    MinVolume          = 2;       // minimal tick volume of bar to allow entries
double TP_Multiplier      = 1.7;     // TP = SL * TP_Multiplier (can be tuned)

//--- Globals
datetime g_lastBarTime    = 0;

//+------------------------------------------------------------------+
//| init                                                             |
//+------------------------------------------------------------------+
int init()
{
   // Clip inputs to safe minimums
   int minStops = (int)MarketInfo(Symbol(), MODE_STOPLEVEL);
   if (TrailingStop <= minStops)
      TrailingStop = minStops + 1;
   if (Step <= minStops)
      Step = minStops + 1;

   g_lastBarTime = Time[0];
   return(0);
}

//+------------------------------------------------------------------+
//| deinit                                                           |
//+------------------------------------------------------------------+
int deinit()
{
   return(0);
}

//+------------------------------------------------------------------+
//| Helper: spread OK?                                               |
//+------------------------------------------------------------------+
bool SpreadOk()
{
   double spr = (Ask - Bid) / Point;
   spr = NormalizeDouble(spr, Digits);
   return (spr <= Max_Spread);
}

//+------------------------------------------------------------------+
//| Helper: normalize & clamp lots                                   |
//+------------------------------------------------------------------+
double NormalizeLots(double lot)
{
   double step = MarketInfo(Symbol(), MODE_LOTSTEP);
   double minL = MarketInfo(Symbol(), MODE_MINLOT);
   double maxL = MarketInfo(Symbol(), MODE_MAXLOT);

   if (step <= 0.0) step = 0.01;
   lot = MathFloor(lot / step) * step;

   if (lot < minL) lot = minL;
   if (lot > maxL) lot = maxL;

   return NormalizeDouble(lot, 2);
}

//+------------------------------------------------------------------+
//| Helper: count orders by type for this symbol+magic              |
//+------------------------------------------------------------------+
int CountOrders(int type)
{
   int count = 0;
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if (OrderSymbol() != Symbol()) continue;
      if (OrderMagicNumber() != Magic) continue;

      if (type < 0 || OrderType() == type)
         count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Helper: delete all pendings of a given type                     |
//+------------------------------------------------------------------+
void DeletePendings(int type)
{
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if (OrderSymbol() != Symbol()) continue;
      if (OrderMagicNumber() != Magic) continue;

      if (OrderType() == type)
         OrderDelete(OrderTicket());
   }
}

//+------------------------------------------------------------------+
//| Helper: trailing for open positions                             |
//+------------------------------------------------------------------+
void TrailPositions()
{
   if (TrailingStop <= 0) return;

   int minStops = (int)MarketInfo(Symbol(), MODE_STOPLEVEL);
   double trailPts = MathMax(TrailingStop, minStops + 1) * Point;

   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if (OrderSymbol() != Symbol()) continue;
      if (OrderMagicNumber() != Magic) continue;

      int    type = OrderType();
      double open = OrderOpenPrice();
      double sl   = OrderStopLoss();
      double tp   = OrderTakeProfit();

      // BUY
      if (type == OP_BUY)
      {
         double newSL = Bid - trailPts;
         newSL = NormalizeDouble(newSL, Digits);

         // only move SL up
         if ((sl == 0.0) || (newSL > sl))
            OrderModify(OrderTicket(), open, newSL, tp, 0, clrBlue);
      }

      // SELL
      if (type == OP_SELL)
      {
         double newSL = Ask + trailPts;
         newSL = NormalizeDouble(newSL, Digits);

         // only move SL down
         if ((sl == 0.0) || (newSL < sl))
            OrderModify(OrderTicket(), open, newSL, tp, 0, clrRed);
      }
   }
}

//+------------------------------------------------------------------+
//| Helper: close all positions if profit target reached            |
//+------------------------------------------------------------------+
void CloseAllOnProfit(double profitTarget)
{
   double totalProfit = 0.0;
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if (OrderSymbol() != Symbol()) continue;
      if (OrderMagicNumber() != Magic) continue;

      totalProfit += OrderProfit() + OrderSwap() + OrderCommission();
   }

   if (totalProfit <= profitTarget)
      return;

   // Close all orders for this symbol+magic
   for (int j = OrdersTotal() - 1; j >= 0; j--)
   {
      if (!OrderSelect(j, SELECT_BY_POS, MODE_TRADES))
         continue;
      if (OrderSymbol() != Symbol()) continue;
      if (OrderMagicNumber() != Magic) continue;

      int    type = OrderType();
      double lots = OrderLots();
      int    ticket = OrderTicket();

      if (type == OP_BUY || type == OP_SELL)
      {
         double price = (type == OP_BUY ? Bid : Ask);
         OrderClose(ticket, lots, price, Slippage, clrWhite);
      }
      if (type == OP_BUYSTOP || type == OP_SELLSTOP)
      {
         OrderDelete(ticket);
      }
   }
}

//+------------------------------------------------------------------+
//| Helper: open pending orders based on SAR + Bands logic          |
//+------------------------------------------------------------------+
void EvaluateEntries()
{
   // Spread & volume filters
   if (!SpreadOk())         return;
   if (Volume[0] < MinVolume) return;

   // Basic lot size validation & margin check
   double lot = NormalizeLots(Lots);
   if (AccountFreeMarginCheck(Symbol(), OP_BUYSTOP, lot) <= 0 ||
       GetLastError() == 134)
   {
      // Not enough margin
      return;
   }

   // Indicators
   double sar    = iSAR(NULL, 0, Sar_period, 0.2, 0);
   double bbUp   = iBands(NULL, 0, 20, 2, 0, PRICE_CLOSE, MODE_UPPER, 0);
   double bbLow  = iBands(NULL, 0, 20, 2, 0, PRICE_CLOSE, MODE_LOWER, 0);

   double ask    = Ask;
   double bid    = Bid;

   // Basic context: only one direction at a time (like your old code)
   int sideState = 0; // 1=buy bias, -1=sell bias, 0=none
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if (OrderSymbol() != Symbol()) continue;
      if (OrderMagicNumber() != Magic) continue;

      int t = OrderType();
      if (t == OP_BUY || t == OP_BUYSTOP)
         sideState = 1;
      if (t == OP_SELL || t == OP_SELLSTOP)
         sideState = -1;
   }

   // Profit target: a simple function of lot size (similar spirit to Ld_FFFD0)
   double profitTarget = lot * 200.0; // adjust if needed
   CloseAllOnProfit(profitTarget);

   // Recalculate side state after possible closes (for safety)
   sideState = 0;
   for (int j = OrdersTotal() - 1; j >= 0; j--)
   {
      if (!OrderSelect(j, SELECT_BY_POS, MODE_TRADES))
         continue;
      if (OrderSymbol() != Symbol()) continue;
      if (OrderMagicNumber() != Magic) continue;

      int t2 = OrderType();
      if (t2 == OP_BUY || t2 == OP_BUYSTOP)
         sideState = 1;
      if (t2 == OP_SELL || t2 == OP_SELLSTOP)
         sideState = -1;
   }

   // Clean pendings if very low volume on bar (similar idea to your old code)
   if (Volume[0] < MinVolume)
   {
      DeletePendings(OP_BUYSTOP);
      DeletePendings(OP_SELLSTOP);
      return;
   }

   // --- BUY setup: Ask far from upper band, SAR below price, no strong sell bias
   bool buySignal = (ask < bbUp - 20 * Point) && (Close[0] > sar);
   if (buySignal && (sideState == 0 || sideState == 1))
   {
      // Delete previous BUYSTOPs if any
      DeletePendings(OP_BUYSTOP);

      double price = NormalizeDouble(ask + Step * Point, Digits);
      double sl    = NormalizeDouble(price - StopLoss * Point, Digits);
      double tp    = NormalizeDouble(price + StopLoss * TP_Multiplier * Point, Digits);

      OrderSend(Symbol(), OP_BUYSTOP, lot, price, Slippage, sl, tp,
                "SuperV7_BUYSTOP", Magic, 0, clrBlue);
   }

   // --- SELL setup: Bid far from lower band, SAR above price, no strong buy bias
   bool sellSignal = (bid > bbLow + 20 * Point) && (Close[0] < sar);
   if (sellSignal && (sideState == 0 || sideState == -1))
   {
      // Delete previous SELLSTOPs if any
      DeletePendings(OP_SELLSTOP);

      double price = NormalizeDouble(bid - Step * Point, Digits);
      double sl    = NormalizeDouble(price + StopLoss * Point, Digits);
      double tp    = NormalizeDouble(price - StopLoss * TP_Multiplier * Point, Digits);

      OrderSend(Symbol(), OP_SELLSTOP, lot, price, Slippage, sl, tp,
                "SuperV7_SELLSTOP", Magic, 0, clrRed);
   }
}

//+------------------------------------------------------------------+
//| start (OnTick in MQL4)                                          |
//+------------------------------------------------------------------+
int start()
{
   // Per-bar logic (housekeeping on new bar)
   if (Time[0] != g_lastBarTime)
   {
      g_lastBarTime = Time[0];
      // Optional: could do per-bar cleanup or stats here
   }

   // 1- Trailing stop management for open positions
   TrailPositions();

   // 2- Entry logic with SAR + Bands + step distance
   EvaluateEntries();

   return(0);
}